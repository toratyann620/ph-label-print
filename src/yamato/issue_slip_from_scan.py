"""
QRコード付き注文明細PDFからヤマト送り状を発行する。

処理フロー:
  1. PDF内のQRコードを読み取り、注文番号（Shopify注文名）を取得
  2. 複数ストア（PHOTOPRI/ARTGRAPH/E1/QOO）から該当注文をShopify APIで検索
  3. ヤマトB2クラウドAPIで送り状を発行
  4. 送り状PDFを出力フォルダ（設定の output_folder、既定は output/）に保存
  5. 発行できたらShopify注文に設定タグ（issue_tag）を付与

各ステップの結果は db.py 経由で shipments テーブルに記録され、
管理画面（処理状況一覧・発行履歴・エラー一覧）に反映される。

スキャンフォルダ一括処理（自動発行モードの「スキャン実行」から呼ばれる）:
  scan_folder_and_issue() は 設定の scan_folder（既定 input/）内のPDFを1件ずつ処理し、
  処理後は 設定の archive_folder（既定 output/archive/）へ移動する。

CLI実行例:
  PYTHONPATH=src/shopify:src/common .venv/bin/python src/yamato/issue_slip_from_scan.py sample/注文明細サンプル.pdf
"""
import asyncio
import glob
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime

import httpx
from dotenv import load_dotenv

# src/sagawa を直接 import できるようにする（PYTHONPATH未設定でも動くように、app.pyと同じ方式）
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SAGAWA_PATH = os.path.join(_SRC_DIR, "sagawa")
if _SAGAWA_PATH not in sys.path:
    sys.path.insert(0, _SAGAWA_PATH)

from config import STORE_CANDIDATES
from shopify_client import ShopifyClient
from qr_reader import extract_order_name_from_pdf
from sagawa_client import issue_sagawa_pdf, format_sagawa_error
import db

load_dotenv(os.getenv("APP_ENV_FILE", ".env"), override=True)

BASE_URL        = os.getenv("YAMATO_API_BASE_URL", "https://testb2api.kuronekoyamato.co.jp")
API_USER_ID     = os.getenv("YAMATO_CUSTOMER_CODE", "")
ACCESS_TOKEN    = os.getenv("YAMATO_API_KEY", "")
INVOICE_CODE    = os.getenv("YAMATO_INVOICE_CODE", "")
INVOICE_EXT     = os.getenv("YAMATO_INVOICE_CODE_EXT", "")
INVOICE_FREIGHT = os.getenv("YAMATO_INVOICE_FREIGHT_NO", "")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _resolve_path(path: str) -> str:
    """設定のフォルダパスをプロジェクトルート基準の絶対パスに解決する"""
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def format_yamato_error(result: dict) -> str:
    """
    issue_yamato_pdf() の失敗結果を、担当者が読んで対処できる形式のメッセージに整形する。
    ヤマトAPIの業務バリデーションエラー（editA_check）は error_description が日本語で
    分かりやすいため、それをそのまま前面に出す。それ以外（HTTP/通信エラー等）は生の情報を残す。
    """
    step = result.get("step", "")
    if step == "editA_check":
        errors = result.get("errors") or []
        if errors:
            lines = [
                f"・{e.get('error_property_name', '?')}: {e.get('error_description', e.get('error_code', '不明なエラー'))}"
                for e in errors
            ]
            return "送り状データの入力内容にエラーがあります（Shopify注文の住所等を確認・修正のうえ再試行してください）:\n" + "\n".join(lines)
        return "送り状データにエラーがありますが、詳細を取得できませんでした。"
    if step == "editA":
        return f"ヤマトAPIへの仮データ登録に失敗しました（HTTP {result.get('status')}）: {result.get('body', '')[:300]}"
    if step in ("new", "polling"):
        return f"ヤマトAPIでの送り状発行処理に失敗しました（HTTP {result.get('status')}）: {result.get('body', '')[:300]}"
    if step == "polling_timeout":
        return "ヤマトAPIの印刷データ作成が時間内に完了しませんでした。時間をおいて再試行してください。"
    if step == "download":
        return f"送り状PDFのダウンロードに失敗しました（HTTP {result.get('status')}）: {result.get('body', '')[:300]}"
    return str(result)


async def find_order(order_name: str):
    """
    設定済みの全ストアから該当する注文を検索する。
    1ストアのAPIエラー（認証切れ等）で検索全体が止まらないよう、他ストアは継続して試す。
    戻り値: (store_name, ShopifyClient, order) / 見つからない場合は (None, None, None)
            store_error_messages: {store: エラー文字列} （呼び出し側でのエラー表示用）
    """
    store_errors: dict[str, str] = {}
    for store in STORE_CANDIDATES:
        try:
            shopify = ShopifyClient(store)
        except ValueError:
            continue
        try:
            order = await shopify.get_order_by_name(order_name)
        except Exception as e:
            store_errors[store] = str(e)
            continue
        if order:
            return store, shopify, order, store_errors
    return None, None, None, store_errors


def _apply_store_settings(yamato_req, store_name: str):
    """店舗設定（管理画面で編集された送り元情報）があれば上書きする"""
    settings = db.get_store_settings(store_name)
    if not settings:
        return yamato_req
    if settings.get("sender_name"):
        yamato_req.sender_name = settings["sender_name"]
    if settings.get("sender_zip"):
        yamato_req.sender_zip = settings["sender_zip"]
    if settings.get("sender_address"):
        yamato_req.sender_address = settings["sender_address"]
    if settings.get("sender_address2"):
        yamato_req.sender_address2 = settings["sender_address2"]
    if settings.get("sender_phone"):
        yamato_req.sender_phone = settings["sender_phone"]
    return yamato_req


def _apply_sagawa_store_settings(sagawa_req: dict, store_name: str) -> dict:
    """店舗設定（管理画面で編集された送り元情報）があれば上書きする（ヤマトの_apply_store_settingsと同様）"""
    settings = db.get_store_settings(store_name)
    if not settings:
        return sagawa_req
    if settings.get("sender_name"):
        sagawa_req["sender_name"] = settings["sender_name"]
    if settings.get("sender_zip"):
        sagawa_req["sender_zip"] = settings["sender_zip"]
    if settings.get("sender_address"):
        sagawa_req["sender_address1"] = settings["sender_address"][:25]
    if settings.get("sender_address2"):
        sagawa_req["sender_address2"] = settings["sender_address2"][:25]
    if settings.get("sender_phone"):
        sagawa_req["sender_phone"] = settings["sender_phone"]
    return sagawa_req


def print_pdf(pdf_path: str, printer_name: str | None = None) -> tuple[bool, str]:
    """送り状PDFをプリンターへ送る。printer_name未指定時はシステムの既定プリンターを使う"""
    if platform.system() == "Windows":
        return _print_pdf_windows(pdf_path, printer_name)
    return _print_pdf_unix(pdf_path, printer_name)


def _print_pdf_unix(pdf_path: str, printer_name: str | None) -> tuple[bool, str]:
    """macOS/Linux: CUPSの lp コマンドを使用"""
    cmd = ["lp"]
    if printer_name:
        cmd += ["-d", printer_name]
    cmd.append(pdf_path)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        message = (result.stdout or result.stderr or "").strip()
        return result.returncode == 0, message
    except Exception as e:
        return False, str(e)


def _list_windows_printers() -> list[str]:
    """このPCにインストールされているプリンター名の一覧を取得する"""
    try:
        import win32print
        # PRINTER_ENUM_LOCAL(2) | PRINTER_ENUM_CONNECTIONS(4)
        return [p[2] for p in win32print.EnumPrinters(2 | 4)]
    except Exception:
        return []


def _print_pdf_windows(pdf_path: str, printer_name: str | None) -> tuple[bool, str]:
    """
    Windows印刷。
    1. SumatraPDF（環境変数 SUMATRA_PDF_PATH、または tools/SumatraPDF.exe）があればそれを使う（推奨・最も確実）
       https://www.sumatrapdfreader.org/ （無料・ポータブル版で可）
    2. 無ければ pywin32 の ShellExecute(printto) にフォールバック（既定のPDFビューアの対応状況に依存するため非推奨）

    印刷前に指定プリンター名がこのPCに実在するかを確認する（設定画面の入力ミス・
    Windows側の登録名との食い違いを、印刷が「成功」した見た目のまま見逃さないため）。
    """
    if printer_name:
        installed = _list_windows_printers()
        if installed and printer_name not in installed:
            return False, (
                f"プリンター『{printer_name}』が見つかりません。"
                f"このPCに登録されているプリンター: {', '.join(installed)}"
                "（設定画面のプリンター名を確認してください）"
            )

    sumatra = os.getenv("SUMATRA_PDF_PATH") or os.path.join(PROJECT_ROOT, "tools", "SumatraPDF.exe")
    target_label = printer_name or "既定のプリンター"
    if os.path.exists(sumatra):
        cmd = [sumatra, "-silent", "-exit-when-done"]
        cmd += ["-print-to", printer_name] if printer_name else ["-print-to-default"]
        cmd.append(pdf_path)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            detail = (result.stdout or result.stderr or "").strip()
            message = f"SumatraPDFで『{target_label}』へ印刷指示を送信しました"
            if detail:
                message += f"（{detail}）"
            return result.returncode == 0, message
        except Exception as e:
            return False, f"SumatraPDF実行エラー（送信先: {target_label}）: {e}"

    try:
        import win32api
        if printer_name:
            win32api.ShellExecute(0, "printto", pdf_path, f'"{printer_name}"', ".", 0)
        else:
            win32api.ShellExecute(0, "print", pdf_path, None, ".", 0)
        return True, f"既定のPDFビューア経由で『{target_label}』へ印刷指示を送信しました（SumatraPDF未導入のためフォールバック実行）"
    except Exception as e:
        return False, f"Windows印刷に失敗しました（送信先: {target_label}）。SumatraPDFの導入を推奨します: {e}"


async def issue_yamato_pdf(client: httpx.AsyncClient, store_name: str, order_no: str, yamato_req) -> tuple[bool, dict]:
    """ヤマトB2クラウドAPIで送り状を発行し、PDFを出力フォルダへ保存する"""
    ship_date = datetime.now().strftime("%Y%m%d")
    # お届け予定日は空欄にし、ヤマト側で最短日を自動計算させる
    # （仕様書: delivery_date は YYYYMMDD または未指定=最短）
    delivery_date = ""

    shipment_data = {
        "shipment_number":              f"SHOP-{order_no}",
        "service_type":                 yamato_req.service_type,
        "is_cool":                      "0",
        "shipment_date":                ship_date,
        "delivery_date":                delivery_date,
        "amount":                       yamato_req.amount,
        "tax_amount":                   yamato_req.tax_amount,
        "is_printing_lot":              "",
        "invoice_code":                 INVOICE_CODE,
        "invoice_code_ext":             INVOICE_EXT,
        "invoice_freight_no":           INVOICE_FREIGHT,
        "invoice_name":                 "",
        "payment_flg":                  "0",
        "payment_number":               "",
        "payment_receipt_no1":          "",
        "payment_receipt_no2":          "",
        "payment_receipt_no3":          "",
        "closure_key":                  "",
        "input_system_type":            "api",
        "package_qty":                  "1",
        "delivery_time_zone":           "",
        "is_using_shipment_email":      "0",
        "is_using_delivery_email":      "0",
        "shipper_telephone_display":    yamato_req.sender_phone,
        "shipper_name":                 yamato_req.sender_name,
        "shipper_zip_code":             yamato_req.sender_zip.replace("-", ""),
        "shipper_address":              yamato_req.sender_address,
        "shipper_address4":             yamato_req.sender_address2,
        "consignee_telephone_display":  yamato_req.recipient_phone,
        "consignee_name":               yamato_req.recipient_name,
        "consignee_zip_code":           yamato_req.recipient_zip.replace("-", ""),
        "consignee_address":            yamato_req.recipient_address,
        "consignee_address4":           yamato_req.recipient_address2,
        "item_name1":                   yamato_req.item_name,
        "is_using_shipment_post_email":     "0",
        "is_using_cons_deli_post_email":    "0",
        "is_using_shipper_deli_post_email": "0",
    }

    payload = {"feed": {"entry": [{"shipment": shipment_data}]}}

    print(f"\n[{order_no}] ヤマトAPI送信データ:")
    print(f"  お届け先: {shipment_data['consignee_name']} / 〒{shipment_data['consignee_zip_code']} {shipment_data['consignee_address']} / {shipment_data['consignee_telephone_display']}")
    print(f"  品名: {shipment_data['item_name1']}")

    # Step 1: 仮データ登録・データチェック
    r1 = await client.post(
        f"{BASE_URL}/b2/p/editA?api_user_id={API_USER_ID}",
        headers={"Authorization": f"Token {ACCESS_TOKEN}", "Content-Type": "application/json"},
        json=payload,
    )
    if r1.status_code != 200:
        return False, {"step": "editA", "status": r1.status_code, "body": r1.text}

    r1_data = r1.json()
    feed = r1_data.get("feed", {})
    entries = feed.get("entry", [])
    updated = feed.get("updated", "")
    if not entries:
        return False, {"step": "editA_parse", "body": r1_data}

    entry = entries[0]
    shipment = entry.get("shipment", {})
    tracking_number = shipment.get("tracking_number", "")
    created_ms = shipment.get("created_ms", "")
    error_flg = shipment.get("error_flg", "0")
    errors = entry.get("error", [])

    if errors:
        print("  ⚠ ヤマトAPIバリデーション:")
        for e in errors:
            print(f"    [{e.get('error_code')}] {e.get('error_property_name')}: {e.get('error_description')}")

    if error_flg == "9":
        return False, {"step": "editA_check", "errors": errors}

    # Step 2: 送り状発行
    # print_type: ネコポス(A)は専用レイアウト(A4 6面付け)固定、それ以外(発払い/コレクト等)はA4マルチ印刷
    service_type_resolved = shipment.get("service_type", "0")
    print_type = "A" if service_type_resolved == "A" else "m"

    issue_shipment = {
        "tracking_number": tracking_number,
        "created_ms":      created_ms,
        "service_type":    service_type_resolved,
        "printer_type":    "1",
        "shipment_flg":    "1",
    }
    if service_type_resolved == "A":
        # ネコポスは必須: 送り状本体("0")か払込票("1")かを指定
        issue_shipment["is_agent"] = "0"

    issue_payload = {
        "feed": {
            "updated": updated,
            "entry": [{
                "id": str(entry.get("id", "1")),
                "shipment": issue_shipment,
            }],
        }
    }
    r2 = await client.post(
        f"{BASE_URL}/b2/p/new?issue_editA&display=0&print_type={print_type}",
        headers={"X-Requested-With": "XMLHttpRequest", "Content-Type": "application/json"},
        json=issue_payload,
    )
    if r2.status_code != 200:
        return False, {"step": "new", "status": r2.status_code, "body": r2.text}

    r2_data = r2.json()
    issue_no = r2_data.get("feed", {}).get("title", "")
    subtitle_ms = int(r2_data.get("feed", {}).get("subtitle", "1000"))
    if not issue_no:
        return False, {"step": "new_parse", "body": r2_data}

    # Step 3: 印刷状態確認（ポーリング）
    wait_sec = max(subtitle_ms / 1000, 1.0)
    rxid = None
    for _ in range(15):
        await asyncio.sleep(wait_sec)
        r3 = await client.get(f"{BASE_URL}/b2/p/polling?issue_no={issue_no}&display=0")
        if r3.status_code == 200:
            rxid = r3.json().get("feed", {}).get("title", "")
            break
        elif r3.status_code == 202:
            wait_sec = max(wait_sec / 2, 1.0)
            continue
        else:
            return False, {"step": "polling", "status": r3.status_code, "body": r3.text}

    if not rxid:
        return False, {"step": "polling_timeout"}

    # Step 4: 印刷データチェック + PDFダウンロード
    await client.get(f"{BASE_URL}/b2/p/getfile?display=0&issue_no={issue_no}&checkonly=1")
    r5 = await client.get(f"{BASE_URL}/b2/p/getfile?display=0&issue_no={issue_no}&fileonly=1")

    if r5.status_code != 200 or len(r5.content) <= 100:
        return False, {"step": "download", "status": r5.status_code, "body": r5.text[:200]}

    output_dir = _resolve_path(db.get_app_settings()["output_folder"])
    os.makedirs(output_dir, exist_ok=True)
    pdf_filename = f"scan_{store_name}_{order_no}_{issue_no}.pdf"
    pdf_path = os.path.join(output_dir, pdf_filename)
    with open(pdf_path, "wb") as f:
        f.write(r5.content)

    # Step 5: 伝票番号取得
    real_tracking = ""
    for attempt in range(3):
        if attempt > 0:
            await asyncio.sleep(3)
        r6 = await client.get(f"{BASE_URL}/b2/p/editA?spool&_RXID={rxid}")
        if r6.status_code == 200:
            spool_feed = r6.json().get("feed", {})
            if spool_feed.get("subtitle") == "204":
                new_rxid = spool_feed.get("title", "")
                if new_rxid and new_rxid != rxid:
                    rxid = new_rxid
                continue
            spool_entries = spool_feed.get("entry", [])
            if spool_entries:
                real_tracking = spool_entries[0].get("shipment", {}).get("tracking_number", "")
            break

    return True, {
        "issue_no": issue_no,
        "tracking_number": real_tracking,
        "pdf_path": pdf_path,
    }


async def issue_for_order_name(order_name: str, source_pdf: str | None = None, skip_print: bool = False) -> dict:
    """
    注文番号（Shopify注文名, 例: "#P33986"）1件を、Shopify注文検索〜ヤマト送り状発行〜
    Shopifyタグ付与まで処理し、db.shipments に記録する。
    スキャン起点（自動発行）・チェックボックス起点（手動発行）の両方から共通で呼ばれる。
    skip_print=True の場合、PDF発行までで印刷は行わない（照合スクリプト等での利用を想定）。
    """
    db.init_db()

    # 二重発行防止: 既に発行完了している注文番号は再度ヤマトAPIを呼ばない
    existing = db.find_shipment_by_order_name(order_name)
    if existing:
        return existing

    record_id = db.create_shipment_record(
        source_pdf=source_pdf,
        order_name=order_name,
        status="processing",
    )

    store_name, shopify, order, store_errors = await find_order(order_name)
    if not order:
        if store_errors:
            db.update_shipment_record(
                record_id,
                status="error_shopify",
                error_message=f"注文 '{order_name}' の検索中にShopify APIエラーが発生しました: {store_errors}",
            )
        else:
            db.update_shipment_record(
                record_id,
                status="error_order_not_found",
                error_message=f"注文 '{order_name}' が見つかりませんでした（検索対象ストア: {', '.join(STORE_CANDIDATES)}）",
            )
        return db.get_shipment(record_id)

    order_no = str(order.get("order_number"))
    # Shopify注文タグから配送業者を自動判定する（処理状況一覧の表示にも使う db.classify_shipping_method と同じ判定）
    carrier = "sagawa" if db.classify_shipping_method(order.get("tags", "")) == "佐川" else "yamato"

    if carrier == "sagawa":
        sagawa_req = _apply_sagawa_store_settings(shopify.map_order_to_sagawa_request(order), store_name)
        db.update_shipment_record(
            record_id,
            store=store_name,
            shopify_order_number=order_no,
            carrier=carrier,
            recipient_name=sagawa_req["recipient_name"],
            recipient_address=f"{sagawa_req['recipient_address1']}{sagawa_req['recipient_address2']}{sagawa_req['recipient_address3']}",
            recipient_phone=sagawa_req["recipient_phone"],
        )

        output_dir = _resolve_path(db.get_app_settings()["output_folder"])
        async with httpx.AsyncClient(timeout=60.0) as client:
            success, result = await issue_sagawa_pdf(client, store_name, order_no, sagawa_req, output_dir)

        if not success:
            db.update_shipment_record(record_id, status="error_sagawa", error_message=format_sagawa_error(result))
            return db.get_shipment(record_id)

        db.update_shipment_record(
            record_id,
            status="done",
            yamato_issue_no="",
            yamato_tracking_no=result["tracking_number"],
            pdf_path=result["pdf_path"],
        )
    else:
        yamato_req = _apply_store_settings(shopify.map_order_to_yamato_request(order), store_name)
        db.update_shipment_record(
            record_id,
            store=store_name,
            shopify_order_number=order_no,
            carrier=carrier,
            recipient_name=yamato_req.recipient_name,
            recipient_address=yamato_req.recipient_address,
            recipient_phone=yamato_req.recipient_phone,
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            success, result = await issue_yamato_pdf(client, store_name, order_no, yamato_req)

        if not success:
            db.update_shipment_record(record_id, status="error_yamato", error_message=format_yamato_error(result))
            return db.get_shipment(record_id)

        db.update_shipment_record(
            record_id,
            status="done",
            yamato_issue_no=result["issue_no"],
            yamato_tracking_no=result["tracking_number"],
            pdf_path=result["pdf_path"],
        )

    db.mark_order_issued(order_name, record_id)

    # Shopify注文へのタグ付与（失敗しても送り状発行自体は成功扱いのまま、タグ状況だけ記録する）
    issue_tag = db.get_app_settings()["issue_tag"]
    if issue_tag:
        try:
            await shopify.add_order_tag(order.get("id"), issue_tag)
            db.update_shipment_record(record_id, tag_status="ok")
        except Exception as e:
            db.update_shipment_record(record_id, tag_status=f"failed: {e}")

    # 送り状PDFの印刷（失敗しても送り状発行自体は成功扱いのまま、印刷状況だけ記録する）
    if skip_print:
        db.update_shipment_record(record_id, print_status="skipped")
    else:
        store_settings = db.get_store_settings(store_name)
        printer_name = (store_settings or {}).get("printer_name") or None
        print_ok, print_message = print_pdf(result["pdf_path"], printer_name)
        db.update_shipment_record(
            record_id,
            print_status=("ok: " + print_message) if print_ok else f"failed: {print_message}",
        )

    return db.get_shipment(record_id)


async def process_scanned_pdf(pdf_path: str) -> dict:
    """スキャンPDF1件をQR読取〜発行まで処理する（QR読取失敗時はerror_qrとして記録）"""
    db.init_db()
    try:
        order_name = extract_order_name_from_pdf(pdf_path)
    except ValueError as e:
        record_id = db.create_shipment_record(
            source_pdf=pdf_path,
            status="error_qr",
            error_message=str(e),
        )
        return db.get_shipment(record_id)

    return await issue_for_order_name(order_name, source_pdf=pdf_path)


async def scan_folder_and_issue() -> list[dict]:
    """
    設定の scan_folder 内のPDFを1件ずつ処理し、処理後は archive_folder に移動する
    （自動発行モードの「スキャン実行」ボタンから呼ばれる）。
    """
    settings = db.get_app_settings()
    scan_dir = _resolve_path(settings["scan_folder"])
    archive_dir = _resolve_path(settings["archive_folder"])
    os.makedirs(scan_dir, exist_ok=True)
    os.makedirs(archive_dir, exist_ok=True)

    pdf_paths = sorted(glob.glob(os.path.join(scan_dir, "*.pdf")))
    results = []
    for pdf_path in pdf_paths:
        record = await process_scanned_pdf(pdf_path)
        results.append(record)

        archive_path = os.path.join(archive_dir, os.path.basename(pdf_path))
        if os.path.exists(archive_path):
            base, ext = os.path.splitext(archive_path)
            archive_path = f"{base}_{datetime.now().strftime('%H%M%S')}{ext}"
        shutil.move(pdf_path, archive_path)

    return results


async def main():
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(PROJECT_ROOT, "sample", "注文明細サンプル.pdf")

    print("=" * 60)
    print("スキャンPDF → QR読取 → Shopify注文取得 → ヤマト送り状発行")
    print(f"入力PDF: {pdf_path}")
    print("=" * 60)

    record = await process_scanned_pdf(pdf_path)

    print("\n" + "=" * 60)
    if record["status"] == "done":
        print("【成功】")
        print(f"  注文番号:     {record['order_name']}")
        print(f"  発行番号:     {record['yamato_issue_no']}")
        print(f"  伝票番号:     {record['yamato_tracking_no']}")
        print(f"  PDF保存先:    {record['pdf_path']}")
        print(f"  タグ付与:     {record['tag_status']}")
    else:
        print("【失敗】")
        print(f"  ステータス: {db.STATUS_LABELS.get(record['status'], record['status'])}")
        print(f"  {record['error_message']}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import os
import sys
import json
from datetime import datetime, timedelta
import httpx
from dotenv import load_dotenv

from shopify_client import ShopifyClient

load_dotenv(override=True)

BASE_URL       = os.getenv("YAMATO_API_BASE_URL", "https://testb2api.kuronekoyamato.co.jp")
API_USER_ID    = os.getenv("YAMATO_CUSTOMER_CODE", "")
ACCESS_TOKEN   = os.getenv("YAMATO_API_KEY", "")
INVOICE_CODE   = os.getenv("YAMATO_INVOICE_CODE", "")
INVOICE_EXT    = os.getenv("YAMATO_INVOICE_CODE_EXT", "")
INVOICE_FREIGHT= os.getenv("YAMATO_INVOICE_FREIGHT_NO", "")


async def issue_yamato_pdf(client: httpx.AsyncClient, store_name: str, order_no: str, yamato_req) -> tuple[bool, dict]:
    """
    ヤマト運輸 B2クラウド APIを呼び出し、送り状PDFを作成・保存する。
    送信リクエストデータとAPI結果の辞書を返す。
    """
    # 登録用データ構造の構築
    ship_date = datetime.now().strftime("%Y%m%d")
    delivery_date = (datetime.now() + timedelta(days=2)).strftime("%Y%m%d")

    shipment_data = {
        "shipment_number":              f"SHOP-{order_no}",
        "service_type":                 yamato_req.service_type,
        "is_cool":                      "0",
        "shipment_date":                ship_date,
        "delivery_date":                delivery_date,
        "amount":                       "0",
        "tax_amount":                   "",
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
        # ─── ご依頼主 ───────────────────────
        "shipper_telephone_display":    yamato_req.sender_phone,
        "shipper_name":                 yamato_req.sender_name,
        "shipper_zip_code":             yamato_req.sender_zip.replace("-", ""),
        "shipper_address":              yamato_req.sender_address,
        # ─── お届け先（Shopifyの注文からマッピング） ───
        "consignee_telephone_display":  yamato_req.recipient_phone,
        "consignee_name":               yamato_req.recipient_name,
        "consignee_zip_code":           yamato_req.recipient_zip.replace("-", ""),
        "consignee_address":            yamato_req.recipient_address,
        # ─── 品名 ────────────────────────────
        "item_name1":                   yamato_req.item_name,
        "is_using_shipment_post_email":     "0",
        "is_using_cons_deli_post_email":    "0",
        "is_using_shipper_deli_post_email": "0",
    }

    payload = {
        "feed": {
            "entry": [
                {
                    "shipment": shipment_data
                }
            ]
        }
    }

    # 実際にヤマトに送信するお届け先情報などのコンソール出力
    print(f"\n[{order_no}] ──────────────────────────────────────────")
    print(f"  ▶ ヤマトAPI送信データ確認 (Shopify連携データ):")
    print(f"    【お届け先】")
    print(f"      氏名:     {shipment_data['consignee_name']}")
    print(f"      郵便番号: {shipment_data['consignee_zip_code']}")
    print(f"      住所:     {shipment_data['consignee_address']}")
    print(f"      電話番号: {shipment_data['consignee_telephone_display']}")
    print(f"    【ご依頼主】")
    print(f"      氏名:     {shipment_data['shipper_name']}")
    print(f"      住所:     {shipment_data['shipper_address']}")
    print(f"    【荷物情報】")
    print(f"      品名:     {shipment_data['item_name1']}")
    print(f"      予定日:   {shipment_data['shipment_date']}")
    print(f"  ──────────────────────────────────────────")

    log_entry = {
        "order_number": order_no,
        "sent_payload": payload,
        "status": "pending",
        "errors": [],
        "tracking_number": "",
        "issue_no": "",
        "pdf_saved_path": ""
    }

    # 1. 仮データ登録・データチェック (POST /b2/p/editA)
    print(f"[{order_no}] [Step 1] 仮データ登録・データチェック送信中...")
    r1 = await client.post(
        f"{BASE_URL}/b2/p/editA?api_user_id={API_USER_ID}",
        headers={
            "Authorization": f"Token {ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        json=payload,
    )
    if r1.status_code != 200:
        print(f"  ✗ エラー (HTTP {r1.status_code}): {r1.text}")
        log_entry["status"] = f"error_editA_http_{r1.status_code}"
        log_entry["response_body"] = r1.text
        return False, log_entry

    r1_data = r1.json()
    feed = r1_data.get("feed", {})
    entries = feed.get("entry", [])
    updated = feed.get("updated", "")

    if not entries:
        print(f"  ✗ entryなし: {r1_data}")
        log_entry["status"] = "error_no_entries"
        log_entry["response_body"] = r1_data
        return False, log_entry

    entry = entries[0]
    shipment = entry.get("shipment", {})
    tracking_number = shipment.get("tracking_number", "")
    created_ms = shipment.get("created_ms", "")
    error_flg = shipment.get("error_flg", "0")
    errors = entry.get("error", [])

    log_entry["errors"] = errors
    log_entry["error_flg"] = error_flg

    if errors:
        print(f"  ⚠ ヤマトAPI側バリデーション警告/エラー:")
        for e in errors:
            print(f"    [{e.get('error_code')}] {e.get('error_property_name')}: {e.get('error_description')}")

    if error_flg == "9":
        print("  ✗ データチェックNG: 出荷データにエラーがあります。処理を中止します。")
        log_entry["status"] = "failed_validation"
        return False, log_entry

    print(f"  ✓ データチェックOK (エラーなし) | 仮伝票番号: {tracking_number}")

    # 2. 送り状発行 (POST /b2/p/new)
    print(f"[{order_no}] [Step 2] 送り状発行要求...")
    issue_payload = {
        "feed": {
            "updated": updated,
            "entry": [
                {
                    "id": str(entry.get("id", "1")),
                    "shipment": {
                        "tracking_number": tracking_number,
                        "created_ms":      created_ms,
                        "service_type":    shipment.get("service_type", "0"),
                        "printer_type":    "1",  # 1: レーザープリンタ
                        "shipment_flg":    "1",
                    },
                }
            ],
        }
    }

    r2 = await client.post(
        f"{BASE_URL}/b2/p/new?issue_editA&display=0&print_type=m",
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/json",
        },
        json=issue_payload,
    )
    if r2.status_code != 200:
        print(f"  ✗ エラー (HTTP {r2.status_code}): {r2.text}")
        log_entry["status"] = f"error_new_http_{r2.status_code}"
        return False, log_entry

    r2_data = r2.json()
    issue_no = r2_data.get("feed", {}).get("title", "")
    subtitle_ms = int(r2_data.get("feed", {}).get("subtitle", "1000"))
    log_entry["issue_no"] = issue_no

    # 3. 印刷状態確認（ポーリング） (GET /b2/p/polling)
    print(f"[{order_no}] [Step 3] 印刷状態確認ポーリング (推定待ち時間: {subtitle_ms}ms)...")
    wait_sec = max(subtitle_ms / 1000, 1.0)
    rxid = None

    for attempt in range(15):
        await asyncio.sleep(wait_sec)
        r3 = await client.get(
            f"{BASE_URL}/b2/p/polling?issue_no={issue_no}&display=0"
        )
        if r3.status_code == 200:
            r3_data = r3.json()
            rxid = r3_data.get("feed", {}).get("title", "")
            break
        elif r3.status_code == 202:
            wait_sec = max(wait_sec / 2, 1.0)
            continue
        else:
            print(f"  ✗ ポーリングエラー (HTTP {r3.status_code}): {r3.text}")
            log_entry["status"] = f"error_polling_http_{r3.status_code}"
            return False, log_entry

    if not rxid:
        print("  ✗ タイムアウト: 印刷準備が完了しませんでした。")
        log_entry["status"] = "error_polling_timeout"
        return False, log_entry

    # 4. 印刷データチェック (GET /b2/p/getfile?checkonly=1)
    await client.get(
        f"{BASE_URL}/b2/p/getfile?display=0&issue_no={issue_no}&checkonly=1"
    )

    # 5. PDFダウンロード (GET /b2/p/getfile?fileonly=1)
    print(f"[{order_no}] [Step 5] PDFダウンロード...")
    r5 = await client.get(
        f"{BASE_URL}/b2/p/getfile?display=0&issue_no={issue_no}&fileonly=1"
    )
    
    pdf_path = ""
    if r5.status_code == 200 and len(r5.content) > 100:
        pdf_filename = f"shopify_{store_name}_{order_no}_{issue_no}.pdf"
        env_folder = os.getenv(f"SHOPIFY_{store_name}_DL_FOLDER", "")
        if env_folder and os.path.exists(env_folder):
            pdf_path = os.path.join(env_folder, pdf_filename)
        else:
            pdf_path = pdf_filename

        with open(pdf_path, "wb") as f:
            f.write(r5.content)
        print(f"  ✓ PDF保存成功: {pdf_path} ({len(r5.content):,} bytes)")
        log_entry["pdf_saved_path"] = pdf_path
    else:
        print(f"  ✗ PDF取得失敗: {r5.text[:200]}")
        log_entry["status"] = "error_download_failed"
        return False, log_entry

    # 6. 伝票番号取得 (GET /b2/p/editA?spool)
    real_tracking = ""
    for spool_attempt in range(3):
        if spool_attempt > 0:
            await asyncio.sleep(3)
        r6 = await client.get(
            f"{BASE_URL}/b2/p/editA?spool&_RXID={rxid}"
        )
        if r6.status_code == 200:
            r6_data = r6.json()
            spool_feed = r6_data.get("feed", {})
            if spool_feed.get("subtitle") == "204":
                new_rxid = spool_feed.get("title", "")
                if new_rxid and new_rxid != rxid:
                    rxid = new_rxid
                continue
            spool_entries = spool_feed.get("entry", [])
            if spool_entries:
                real_tracking = spool_entries[0].get("shipment", {}).get("tracking_number", "")
            break

    print(f"  ✓ 伝票番号（お問い合せ送り状番号）確定: {real_tracking or '取得失敗（仮番号）'}")
    log_entry["tracking_number"] = real_tracking
    log_entry["status"] = "success"
    return True, log_entry


async def main():
    store_name = "PHOTOPRI"
    print("=" * 60)
    print(f"Shopifyストア「{store_name}」注文情報からヤマト送り状作成開始")
    print(" (送信データ可視化デバッグモード)")
    print("=" * 60)

    try:
        shopify = ShopifyClient(store_name)
    except Exception as e:
        print(f"Shopifyクライアントの初期化エラー: {e}")
        return

    # Shopifyから最新3件の注文を取得
    print("最新の注文情報を取得中...")
    try:
        orders = await shopify.get_latest_orders(limit=1)
    except Exception as e:
        print(f"Shopify注文情報の取得失敗: {e}")
        return

    if not orders:
        print("注文が見つかりませんでした。")
        return

    print(f"注文を取得しました（計 {len(orders)} 件）")
    for i, order in enumerate(orders):
        order_no = order.get("order_number")
        name = order.get("shipping_address", {}).get("name", "宛名不明")
        created_at = order.get("created_at")
        print(f"  [{i+1}] 注文番号: #{order_no} | 購入者: {name} | 注文日時: {created_at}")

    sent_logs = []

    async with httpx.AsyncClient(timeout=60.0) as http_client:
        for order in orders:
            order_no = str(order.get("order_number"))
            print(f"\n--- 注文 #{order_no} のヤマト送り状データ処理開始 ---")
            
            # ヤマト用のリクエストデータにマッピング
            yamato_req = shopify.map_order_to_yamato_request(order)
            
            # ヤマトAPIを呼び出してPDF生成＆送信ログ取得
            success, log_entry = await issue_yamato_pdf(http_client, store_name, order_no, yamato_req)
            sent_logs.append(log_entry)
            
            if success:
                print(f"注文 #{order_no} の送り状作成に成功しました。")
            else:
                print(f"注文 #{order_no} の送り状作成に失敗しました。")

    # 送信したリクエストログをJSONファイルに保存
    log_file_path = "yamato_last_requests.json"
    with open(log_file_path, "w", encoding="utf-8") as f:
        json.dump(sent_logs, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("【処理完了】")
    print(f"  実際にヤマト運輸APIへ送信したデータ（JSON）を以下に保存しました:")
    print(f"  ファイル: {os.path.abspath(log_file_path)}")
    print("  このファイルを開くことで、Shopifyから正しく住所や氏名が抽出され、")
    print("  ヤマトAPIへ送信されていることを確認できます。")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

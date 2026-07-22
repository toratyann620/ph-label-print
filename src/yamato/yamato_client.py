"""
ヤマト運輸 B2クラウド API クライアント

仕様書（APIデータ交換規約4.7版）より判明した仕様:
  - 認証: HTTPヘッダー "Authorization: Token {Accesstoken}"
          ※ "Token " の後に半角スペースが必要
          ※ 最初のリクエスト（仮データ登録）のみ設定。以降はCookieのセッションIDで認証。
  - API連携会社コード: URLパラメータ api_user_id に設定
  - フォーマット: JSON, UTF-8
  - プロトコル: HTTPS REST (GET/POST/PUT)
  - データ構造: feed > entry[] > shipment

フロー（画面API利用なし）:
  1. POST /b2/p/editA?api_user_id=XXX  ← 仮データ登録・データチェック
  2. POST /b2/p/new?issue_editA&display=0&print_type=m  ← 送り状発行
  3. GET  /b2/p/polling?issue_no=xxx&display=0  ← 印刷状態確認（完了まで繰り返す）
  4. GET  /b2/p/getfile?display=0&issue_no=xxx&fileonly=1  ← PDF取得
  5. GET  /b2/p/editA?spool&_RXID=xxx  ← 伝票番号取得
"""

import os
import asyncio
import httpx
from dotenv import load_dotenv
from models import ShipmentRequest, ShipmentResponse

load_dotenv(os.getenv("APP_ENV_FILE", ".env"), override=True)

YAMATO_API_BASE_URL = os.getenv("YAMATO_API_BASE_URL", "https://testb2api.kuronekoyamato.co.jp")
CUSTOMER_CODE       = os.getenv("YAMATO_CUSTOMER_CODE", "")
API_KEY             = os.getenv("YAMATO_API_KEY", "")

# 仕様書より: Authorization: Token {Accesstoken}
# 検証環境では、YAMATO_API_KEY の値をそのまま Accesstoken として使う
ACCESS_TOKEN = API_KEY


def _make_auth_headers() -> dict:
    """最初のリクエスト（仮データ登録）に使用するヘッダー"""
    return {
        "Authorization": f"Token {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _make_session_headers() -> dict:
    """2回目以降のリクエストに使用するヘッダー（Authorizationなし）"""
    return {
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/json",
    }


def _build_shipment_feed(req: ShipmentRequest) -> dict:
    """仮データ登録用の出荷データJSON（feed > entry[] > shipment 形式）"""
    from datetime import datetime
    today = datetime.now().strftime("%Y%m%d")
    shipment_date = req.ship_date.replace("-", "") if req.ship_date else today

    return {
        "feed": {
            "entry": [
                {
                    "shipment": {
                        "shipment_number":             req.customer_order_no or "",
                        "service_type":                req.service_type or "0",
                        "is_cool":                     "0",
                        "shipment_date":               shipment_date,
                        "delivery_date":               "",
                        "amount":                      "0",
                        "tax_amount":                  "",
                        "is_printing_lot":             "",
                        "invoice_code":                os.getenv("YAMATO_INVOICE_CODE", ""),
                        "invoice_code_ext":            os.getenv("YAMATO_INVOICE_CODE_EXT", ""),
                        "invoice_freight_no":          os.getenv("YAMATO_INVOICE_FREIGHT_NO", ""),
                        "invoice_name":                "",
                        "payment_flg":                 "0",
                        "payment_number":              "",
                        "payment_receipt_no1":         "",
                        "payment_receipt_no2":         "",
                        "payment_receipt_no3":         "",
                        "closure_key":                 "",
                        "input_system_type":           "api",
                        "package_qty":                 str(req.total_count or 1),
                        "delivery_time_zone":          "",
                        "is_using_shipment_email":     "0",
                        "is_using_delivery_email":     "0",
                        "shipper_telephone_display":   req.sender_phone or "",
                        "shipper_name":                req.sender_name or "",
                        "shipper_zip_code":            (req.sender_zip or "").replace("-", ""),
                        "shipper_address":             req.sender_address or "",
                        "consignee_telephone_display": req.recipient_phone or "",
                        "consignee_name":              req.recipient_name or "",
                        "consignee_zip_code":          (req.recipient_zip or "").replace("-", ""),
                        "consignee_address":           req.recipient_address or "",
                        "item_name1":                  req.item_name or "",
                        "is_using_shipment_post_email": "0",
                        "is_using_cons_deli_post_email": "0",
                        "is_using_shipper_deli_post_email": "0",
                    }
                }
            ]
        }
    }


async def create_shipment(req: ShipmentRequest) -> ShipmentResponse:
    """
    送り状発行フロー（画面API利用なし）

    1. 仮データ登録・データチェック (POST /b2/p/editA)
    2. 送り状発行 (POST /b2/p/new)
    3. 印刷状態確認 (GET /b2/p/polling) ← 完了までポーリング
    4. 伝票番号取得 (GET /b2/p/editA?spool)
    """
    base = YAMATO_API_BASE_URL
    api_user_id = CUSTOMER_CODE

    async with httpx.AsyncClient(timeout=30.0) as client:

        # ─── Step 1: 仮データ登録・データチェック ───────────────────────
        edit_url = f"{base}/b2/p/editA?api_user_id={api_user_id}"
        payload = _build_shipment_feed(req)

        r1 = await client.post(edit_url, headers=_make_auth_headers(), json=payload)
        r1_data = r1.json() if r1.headers.get("content-type", "").startswith("application/json") else {}

        if r1.status_code != 200:
            return ShipmentResponse(
                success=False,
                slip_no="",
                raw={"step": "editA", "status": r1.status_code, "body": r1.text},
            )

        feed = r1_data.get("feed", {})
        entries = feed.get("entry", [])
        if not entries:
            return ShipmentResponse(
                success=False,
                slip_no="",
                raw={"step": "editA_parse", "message": "エントリーなし", "body": r1_data},
            )

        entry = entries[0]
        shipment = entry.get("shipment", {})
        tracking_number = shipment.get("tracking_number", "")
        created_ms = shipment.get("created_ms", "")
        updated = feed.get("updated", "")
        error_flg = shipment.get("error_flg", "0")
        errors = entry.get("error", [])

        # エラーフラグ=9 の場合は業務エラー
        if error_flg == "9":
            return ShipmentResponse(
                success=False,
                slip_no="",
                raw={
                    "step": "editA_check",
                    "message": "出荷データにエラーあり",
                    "errors": errors,
                    "error_flg": error_flg,
                },
            )

        service_type = shipment.get("service_type", req.service_type or "0")

        # ─── Step 2: 送り状発行 ─────────────────────────────────────────
        issue_url = f"{base}/b2/p/new?issue_editA&display=0&print_type=m"
        issue_payload = {
            "feed": {
                "updated": updated,
                "entry": [
                    {
                        "id": str(entry.get("id", "1")),
                        "shipment": {
                            "tracking_number": tracking_number,
                            "created_ms":      created_ms,
                            "service_type":    service_type,
                            "printer_type":    "1",
                            "shipment_flg":    "1",
                        },
                    }
                ],
            }
        }

        r2 = await client.post(issue_url, headers=_make_session_headers(), json=issue_payload)
        if r2.status_code != 200:
            return ShipmentResponse(
                success=False,
                slip_no="",
                raw={"step": "new", "status": r2.status_code, "body": r2.text},
            )

        r2_data = r2.json()
        issue_no = r2_data.get("feed", {}).get("title", "")
        subtitle_ms = int(r2_data.get("feed", {}).get("subtitle", "1000"))

        if not issue_no:
            return ShipmentResponse(
                success=False,
                slip_no="",
                raw={"step": "new_parse", "message": "発行番号が取得できませんでした", "body": r2_data},
            )

        # ─── Step 3: 印刷状態確認 ───────────────────────────────────────
        polling_url = f"{base}/b2/p/polling?issue_no={issue_no}&display=0"
        wait_sec = max(subtitle_ms / 1000, 1.0)
        rxid = None

        for attempt in range(15):
            await asyncio.sleep(wait_sec)
            r3 = await client.get(polling_url)
            if r3.status_code == 200:
                r3_data = r3.json()
                rxid = r3_data.get("feed", {}).get("title", "")
                break
            elif r3.status_code == 202:
                # まだ作成中
                wait_sec = max(wait_sec / 2, 1.0)
                continue
            else:
                return ShipmentResponse(
                    success=False,
                    slip_no="",
                    raw={"step": "polling", "status": r3.status_code, "body": r3.text},
                )

        if not rxid:
            return ShipmentResponse(
                success=False,
                slip_no="",
                raw={"step": "polling_timeout", "message": "印刷状態が完了になりませんでした"},
            )

        # ─── Step 4: 伝票番号取得 ───────────────────────────────────────
        # 仕様書: 件数0の場合はHTTP 200で {"title":"Error","subtitle":"204"} が返る → 3秒×3回リトライ
        spool_url = f"{base}/b2/p/editA?spool&_RXID={rxid}"
        real_tracking = ""
        r4_data = {}

        for spool_attempt in range(3):
            if spool_attempt > 0:
                await asyncio.sleep(3)
            r4 = await client.get(spool_url)
            if r4.status_code == 200:
                r4_data = r4.json()
                spool_feed = r4_data.get("feed", {})
                # "subtitle":"204" は件数0 → リトライ
                if spool_feed.get("subtitle") == "204":
                    # RXIDを更新してリトライ（Cookieに次のRXIDが設定される）
                    new_rxid = spool_feed.get("title", "")
                    if new_rxid and new_rxid != rxid:
                        spool_url = f"{base}/b2/p/editA?spool&_RXID={new_rxid}"
                    continue
                spool_entries = spool_feed.get("entry", [])
                if spool_entries:
                    real_tracking = spool_entries[0].get("shipment", {}).get("tracking_number", "")
                break
            else:
                break

        return ShipmentResponse(
            success=True,
            slip_no=real_tracking or issue_no,
            raw=r4_data if r4_data else {"issue_no": issue_no},
        )

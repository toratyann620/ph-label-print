"""
ネコポス送り状 発行テスト（ダミーデータ）

ネコポスは通常の宅急便系（発払い等）とは異なるパラメータが必要:
  - service_type = "A"（ネコポス）
  - print_type   = "A"（ネコポス専用レイアウト。固定でA4 6面付け）
  - is_agent     = "0"（送り状本体。払込票の場合は"1"）
"""
import asyncio
import os
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv

load_dotenv(override=True)

BASE_URL       = os.getenv("YAMATO_API_BASE_URL", "https://testb2api.kuronekoyamato.co.jp")
API_USER_ID    = os.getenv("YAMATO_CUSTOMER_CODE", "")
ACCESS_TOKEN   = os.getenv("YAMATO_API_KEY", "")
INVOICE_CODE   = os.getenv("YAMATO_INVOICE_CODE", "")
INVOICE_EXT    = os.getenv("YAMATO_INVOICE_CODE_EXT", "")
INVOICE_FREIGHT= os.getenv("YAMATO_INVOICE_FREIGHT_NO", "")

today = datetime.now()
ship_date = today.strftime("%Y%m%d")
delivery_date = (today + timedelta(days=2)).strftime("%Y%m%d")

SAMPLE_SHIPMENT = {
    "feed": {
        "entry": [
            {
                "shipment": {
                    "shipment_number":              "NEKOPOS-TEST-001",
                    "service_type":                 "A",     # A: ネコポス
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
                    "shipper_telephone_display":    "070-9296-0635",
                    "shipper_name":                 "株式会社PHOTOPRI",
                    "shipper_zip_code":             "1730004",
                    "shipper_address":              "東京都板橋区板橋１丁目９−１０ 3F",
                    # ─── お届け先 ────────────────────────
                    "consignee_telephone_display":  "06-9876-5432",
                    "consignee_name":               "田中　太郎",
                    "consignee_zip_code":           "5300001",
                    "consignee_address":            "大阪府大阪市北区梅田1-1-1",
                    "consignee_address4":           "梅田スカイビル2F",
                    # ─── 品名 ────────────────────────────
                    "item_name1":                   "ネコポステスト商品",
                    # ─── その他 ──────────────────────────
                    "is_using_shipment_post_email":     "0",
                    "is_using_cons_deli_post_email":    "0",
                    "is_using_shipper_deli_post_email": "0",
                }
            }
        ]
    }
}


async def main():
    print("=" * 60)
    print("ネコポス送り状発行テスト")
    print(f"環境: {BASE_URL}")
    print(f"API連携会社コード: {API_USER_ID}")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=60.0) as client:

        # ── Step 1: 仮データ登録・データチェック ──────────────────
        print("\n[Step 1] 仮データ登録・データチェック...")
        r1 = await client.post(
            f"{BASE_URL}/b2/p/editA?api_user_id={API_USER_ID}",
            headers={
                "Authorization": f"Token {ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            json=SAMPLE_SHIPMENT,
        )
        print(f"  → HTTP {r1.status_code}")
        if r1.status_code != 200:
            print(f"  ✗ エラー: {r1.text}")
            return

        r1_data = r1.json()
        feed = r1_data.get("feed", {})
        entries = feed.get("entry", [])
        updated = feed.get("updated", "")

        if not entries:
            print(f"  ✗ entryなし: {r1_data}")
            return

        entry = entries[0]
        shipment = entry.get("shipment", {})
        tracking_number = shipment.get("tracking_number", "")
        created_ms = shipment.get("created_ms", "")
        error_flg = shipment.get("error_flg", "0")
        errors = entry.get("error", [])

        print(f"  仮tracking_number: {tracking_number}")
        print(f"  service_type: {shipment.get('service_type')}")
        print(f"  error_flg: {error_flg}")

        if errors:
            print(f"  ⚠ 業務エラー:")
            for e in errors:
                print(f"    [{e.get('error_code')}] {e.get('error_property_name')}: {e.get('error_description')}")

        if error_flg == "9":
            print("  ✗ 出荷データにエラーあり。修正が必要です。")
            return

        print("  ✓ 仮データ登録 成功")

        # ── Step 2: 送り状発行（ネコポス専用 print_type=A） ────────
        print("\n[Step 2] 送り状発行（print_type=A / ネコポス）...")
        issue_payload = {
            "feed": {
                "updated": updated,
                "entry": [
                    {
                        "id": str(entry.get("id", "1")),
                        "shipment": {
                            "tracking_number": tracking_number,
                            "created_ms":      created_ms,
                            "service_type":    shipment.get("service_type", "A"),
                            "printer_type":    "1",   # 1: レーザー
                            "is_agent":        "0",   # 0: ネコポス送り状本体（1なら払込票）
                            "shipment_flg":    "1",
                        },
                    }
                ],
            }
        }

        r2 = await client.post(
            f"{BASE_URL}/b2/p/new?issue_editA&display=0&print_type=A",
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/json",
            },
            json=issue_payload,
        )
        print(f"  → HTTP {r2.status_code}")
        if r2.status_code != 200:
            print(f"  ✗ エラー: {r2.text}")
            return

        r2_data = r2.json()
        issue_no = r2_data.get("feed", {}).get("title", "")
        subtitle_ms = int(r2_data.get("feed", {}).get("subtitle", "1000"))
        print(f"  発行番号(issue_no): {issue_no}")
        print(f"  帳票生成想定時間: {subtitle_ms}ms")
        print("  ✓ 送り状発行 成功")

        # ── Step 3: 印刷状態確認（ポーリング） ────────────────────
        print("\n[Step 3] 印刷状態確認（ポーリング）...")
        wait_sec = max(subtitle_ms / 1000, 1.0)
        rxid = None

        for attempt in range(15):
            await asyncio.sleep(wait_sec)
            r3 = await client.get(
                f"{BASE_URL}/b2/p/polling?issue_no={issue_no}&display=0"
            )
            print(f"  試行{attempt+1}: HTTP {r3.status_code}")

            if r3.status_code == 200:
                r3_data = r3.json()
                rxid = r3_data.get("feed", {}).get("title", "")
                print(f"  ✓ 作成完了 RXID: {rxid[:30]}...")
                break
            elif r3.status_code == 202:
                print(f"  作成中... {wait_sec:.1f}秒後に再確認")
                wait_sec = max(wait_sec / 2, 1.0)
            else:
                print(f"  ✗ ポーリングエラー: {r3.text}")
                break

        if not rxid:
            print("  ✗ 印刷状態が完了になりませんでした")
            return

        # ── Step 4: PDFダウンロード ───────────────────────────────
        print("\n[Step 4] PDFダウンロード...")
        await client.get(f"{BASE_URL}/b2/p/getfile?display=0&issue_no={issue_no}&checkonly=1")
        r5 = await client.get(
            f"{BASE_URL}/b2/p/getfile?display=0&issue_no={issue_no}&fileonly=1"
        )
        print(f"  → HTTP {r5.status_code}")
        print(f"  Content-Type: {r5.headers.get('content-type', 'N/A')}")

        pdf_path = None
        if r5.status_code == 200 and len(r5.content) > 100:
            pdf_path = f"output/nekopos_test_{issue_no}.pdf"
            with open(pdf_path, "wb") as f:
                f.write(r5.content)
            print(f"  ✓ PDF保存成功: {pdf_path} ({len(r5.content):,} bytes)")
        else:
            print(f"  ✗ PDF取得失敗またはPDF形式でない: {r5.text[:200]}")

        # ── Step 5: 伝票番号取得 ─────────────────────────────────
        print("\n[Step 5] 伝票番号取得...")
        real_tracking = ""
        for spool_attempt in range(3):
            if spool_attempt > 0:
                await asyncio.sleep(3)
            r6 = await client.get(
                f"{BASE_URL}/b2/p/editA?spool&_RXID={rxid}"
            )
            print(f"  試行{spool_attempt+1}: HTTP {r6.status_code}")
            if r6.status_code == 200:
                r6_data = r6.json()
                spool_feed = r6_data.get("feed", {})
                if spool_feed.get("subtitle") == "204":
                    new_rxid = spool_feed.get("title", "")
                    print(f"  No entry(204) → リトライ RXID={new_rxid[:30] if new_rxid else ''}...")
                    if new_rxid and new_rxid != rxid:
                        rxid = new_rxid
                    continue
                spool_entries = spool_feed.get("entry", [])
                if spool_entries:
                    real_tracking = spool_entries[0].get("shipment", {}).get("tracking_number", "")
                break

        print("\n" + "=" * 60)
        print("【テスト結果まとめ】")
        print(f"  発行番号(issue_no): {issue_no}")
        print(f"  伝票番号(tracking_number): {real_tracking or '取得中'}")
        if pdf_path:
            print(f"  PDF: {pdf_path}")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

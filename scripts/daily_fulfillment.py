"""
送り状発行済み（status='done'）の注文をShopify上で「発送済み」（フルフィルメント）にする
日次バッチ処理。notify_customer=Trueにより、Shopifyから顧客へ発送通知メールが自動送信される。

対象は shopify_fulfillment_status が未設定（NULL/空）の shipments レコードのみ。
この機能を導入したタイミングで既に「発行完了」だった注文は 'skipped_backlog' として
自動的に除外されているため、導入後に新たに発行された注文のみが対象になる
（db.py の init_db() 参照）。

Windows Task Scheduler から毎日18:00に実行する（windows/register_fulfillment_task.ps1）。

実行例（プロジェクトルートで実行）:
  .venv\\Scripts\\python.exe scripts\\daily_fulfillment.py   (Windows)
  .venv/bin/python scripts/daily_fulfillment.py              (macOS/Linux)
"""
import asyncio
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("common", "shopify"):
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src", _sub))

import db  # noqa: E402
from shopify_client import ShopifyClient  # noqa: E402

# Shopifyがトラッキングリンク自動生成のために認識する配送会社名の表記
TRACKING_COMPANY = {
    "yamato": "Yamato Transport",
    "sagawa": "Sagawa Express",
}


async def main():
    db.init_db()
    rows = db.list_shipments(statuses=["done"])
    targets = [r for r in rows if not r.get("shopify_fulfillment_status")]

    print(f"対象件数: {len(targets)}")
    if not targets:
        print("対象の注文はありませんでした。")
        return

    ok_count = 0
    for row in targets:
        order_name = row["order_name"]
        store = row["store"]
        tracking_number = row.get("yamato_tracking_no") or ""
        carrier = row.get("carrier") or "yamato"
        tracking_company = TRACKING_COMPANY.get(carrier, "")

        try:
            shopify = ShopifyClient(store)
            order = await shopify.get_order_by_name(order_name)
            if not order:
                db.update_shipment_record(row["id"], shopify_fulfillment_status="failed: 注文が見つかりません")
                print(f"  [NG] {order_name}: 注文が見つかりません")
                continue

            await shopify.fulfill_order(order["id"], tracking_number, tracking_company)
            db.update_shipment_record(row["id"], shopify_fulfillment_status="ok")
            ok_count += 1
            print(f"  [OK] {order_name}")
        except Exception as e:
            db.update_shipment_record(row["id"], shopify_fulfillment_status=f"failed: {e}")
            print(f"  [NG] {order_name}: {e}")

    print(f"完了: {ok_count}/{len(targets)} 件を発送済みにしました。")


if __name__ == "__main__":
    asyncio.run(main())

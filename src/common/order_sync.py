"""
Shopify直近注文の同期ロジック

各ストアの直近N日間の注文をShopify APIから取得し、注文タグから発送方法（ヤマト/佐川/その他）を
判定してdb.orders_cacheに保存する。既に送り状発行済み（shipmentsテーブルにdone状態のレコードが
ある）注文には yamato_status='issued' を反映する。
"""
from config import STORE_CANDIDATES
from shopify_client import ShopifyClient
import db


async def sync_recent_orders(days: int = 7) -> dict:
    """
    設定済みの全ストアの直近注文をorders_cacheに同期する。
    戻り値は {store: 件数 または エラー文字列} の内訳。
    """
    result = {}
    for store in STORE_CANDIDATES:
        try:
            client = ShopifyClient(store)
        except ValueError as e:
            result[store] = f"設定なし: {e}"
            continue

        try:
            orders = await client.get_recent_orders(days=days)
        except Exception as e:
            result[store] = f"取得失敗: {e}"
            continue

        for order in orders:
            recipient = client.extract_recipient(order)
            tags = order.get("tags", "") or ""
            order_name = order.get("name", "")
            shipment = db.find_shipment_by_order_name(order_name)

            db.upsert_order_cache(
                order_id=order.get("id"),
                store=store,
                order_number=str(order.get("order_number") or ""),
                order_name=order_name,
                recipient_name=recipient["name"],
                recipient_address=recipient["address"],
                recipient_phone=recipient["phone"],
                tags=tags,
                shipping_method=db.classify_shipping_method(tags),
                order_created_at=order.get("created_at", ""),
                yamato_status="issued" if shipment else "not_issued",
                shipment_id=shipment["id"] if shipment else None,
            )

        result[store] = len(orders)

    return result

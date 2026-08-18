from pydantic import BaseModel
from typing import Optional, Any


class ShipmentRequest(BaseModel):
    # 受注番号（任意）
    customer_order_no: str = ""

    # 届先
    recipient_name: str
    recipient_zip: str       # 例: "123-4567"
    recipient_address: str
    recipient_address2: str = ""   # 建物名等（consignee_address4）。都道府県〜番地までと分けて送る
    recipient_phone: str

    # 送り元
    sender_name: str
    sender_zip: str
    sender_address: str
    sender_address2: str = ""      # 建物名等（shipper_address4）
    sender_phone: str

    # 荷物
    item_name: str = "商品"
    total_count: int = 1
    weight_kg: float = 1.0
    service_type: str = "0030"   # 0030=宅急便
    ship_date: str               # 例: "2026-03-27"

    # コレクト（代金引換）の場合のみ使用
    amount: str = "0"            # コレクト代金引換額
    tax_amount: str = ""         # コレクト内消費税額等


class ShipmentResponse(BaseModel):
    success: bool
    slip_no: str = ""
    label_url: Optional[str] = None
    error: Optional[str] = None
    raw: Optional[Any] = None


# Shopify Webhook から受け取る注文データのモデル（将来対応）
class ShopifyOrder(BaseModel):
    id: int
    name: str                            # 注文番号 (#1001 など)
    shipping_address: dict
    line_items: list
    note: Optional[str] = None


# スマホ画面での住所修正内容（文字数オーバー時の自動調整結果の手動編集、
# または郵便番号照合での不一致時にどちらの住所を使うかの選択・編集の両方で使う）
class RecipientOverride(BaseModel):
    recipient_name: str
    recipient_zip: str
    recipient_phone: str
    address_lines: list[str]   # 1〜3行。キャリアに応じて発行処理側でマッピングする


# スマホQRスキャン画面からのリクエスト
class ScanOrderRequest(BaseModel):
    order_name: str
    override: Optional[RecipientOverride] = None

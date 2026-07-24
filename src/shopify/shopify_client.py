import os
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv
from models import ShipmentRequest
import db

load_dotenv(os.getenv("APP_ENV_FILE", ".env"), override=True)

PROVINCE_MAP = {
    "01": "北海道", "02": "青森県", "03": "岩手県", "04": "宮城県", "05": "秋田県",
    "06": "山形県", "07": "福島県", "08": "茨城県", "09": "栃木県", "10": "群馬県",
    "11": "埼玉県", "12": "千葉県", "13": "東京都", "14": "神奈川県", "15": "新潟県",
    "16": "富山県", "17": "石川県", "18": "福井県", "19": "山梨県", "20": "長野県",
    "21": "岐阜県", "22": "静岡県", "23": "愛知県", "24": "三重県", "25": "滋賀県",
    "26": "京都府", "27": "大阪府", "28": "兵庫県", "29": "奈良県", "30": "和歌山県",
    "31": "鳥取県", "32": "島根県", "33": "岡山県", "34": "広島県", "35": "山口県",
    "36": "徳島県", "37": "香川県", "38": "愛媛県", "39": "高知県", "40": "福岡県",
    "41": "佐賀県", "42": "長崎県", "43": "熊本県", "44": "大分県", "45": "宮崎県",
    "46": "鹿児島県", "47": "沖縄県"
}

EN_PROVINCE_MAP = {
    "hokkaido": "北海道", "aomori": "青森県", "iwate": "岩手県", "miyagi": "宮城県", "akita": "秋田県",
    "yamagata": "山形県", "fukushima": "福島県", "ibaraki": "茨城県", "tochigi": "栃木県", "gunma": "群馬県",
    "saitama": "埼玉県", "chiba": "千葉県", "tokyo": "東京都", "kanagawa": "神奈川県", "niigata": "新潟県",
    "toyama": "富山県", "ishikawa": "石川県", "fukui": "福井県", "yamanashi": "山梨県", "nagano": "長野県",
    "gifu": "岐阜県", "shizuoka": "静岡県", "aichi": "愛知県", "mie": "三重県", "shiga": "滋賀県",
    "kyoto": "京都府", "osaka": "大阪府", "hyogo": "兵庫県", "nara": "奈良県", "wakayama": "和歌山県",
    "tottori": "鳥取県", "shimane": "島根県", "okayama": "岡山県", "hiroshima": "広島県", "yamaguchi": "山口県",
    "tokushima": "徳島県", "kagawa": "香川県", "ehime": "愛媛県", "kochi": "高知県", "fukuoka": "福岡県",
    "saga": "佐賀県", "nagasaki": "長崎県", "kumamoto": "熊本県", "oita": "大分県", "miyazaki": "宮崎県",
    "kagoshima": "鹿児島県", "okinawa": "沖縄県"
}

def clean_phone(phone: str) -> str:
    if not phone:
        return ""
    # スペースやハイフンを除去
    cleaned = phone.replace(" ", "").replace("-", "")
    # 国際番号 (+81) を 0 に置換
    if cleaned.startswith("+81"):
        cleaned = "0" + cleaned[3:]
    return cleaned

class ShopifyClient:
    def __init__(self, store_prefix: str = "PHOTOPRI"):
        """
        store_prefix: 設定ファイル(.env)におけるショップのプレフィックス (例: ARTGRAPH, E1, PHOTOPRI, QOO)
        """
        self.store_prefix = store_prefix.upper()
        self.shop_url = os.getenv(f"SHOPIFY_{self.store_prefix}_SHOP")
        self.token = os.getenv(f"SHOPIFY_{self.store_prefix}_TOKEN")
        self.dl_folder = os.getenv(f"SHOPIFY_{self.store_prefix}_DL_FOLDER")
        self.api_version = os.getenv("SHOPIFY_API_VERSION", "2024-04")
        
        if not self.shop_url or not self.token:
            raise ValueError(f"Shopify configuration for {self.store_prefix} is missing or incomplete in .env file.")

    async def get_latest_orders(self, limit: int = 3) -> list:
        """
        Shopify REST APIから最新の注文情報を取得する
        """
        params = {"status": "any", "limit": limit, "order": "created_at desc"}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(self._orders_url(), headers=self._headers(), params=params)
            if response.status_code != 200:
                raise Exception(f"Failed to fetch orders from Shopify ({self.shop_url}): {response.status_code} - {response.text}")
            return response.json().get("orders", [])

    def _orders_url(self) -> str:
        shop_domain = self.shop_url
        if not shop_domain.startswith("http"):
            return f"https://{shop_domain}/admin/api/{self.api_version}/orders.json"
        return f"{shop_domain}/admin/api/{self.api_version}/orders.json"

    def _headers(self) -> dict:
        return {
            "X-Shopify-Access-Token": self.token,
            "Content-Type": "application/json",
        }

    async def get_recent_orders(self, days: int = 7, limit: int = 250) -> list:
        """
        直近N日間の注文を取得する（処理状況一覧のShopify注文キャッシュ用）
        """
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        params = {"status": "any", "created_at_min": since, "limit": limit, "order": "created_at desc"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(self._orders_url(), headers=self._headers(), params=params)
            if response.status_code != 200:
                raise Exception(f"Failed to fetch recent orders from Shopify ({self.shop_url}): {response.status_code} - {response.text}")
            return response.json().get("orders", [])

    async def add_order_tag(self, order_id: int, tag: str) -> None:
        """
        注文に新しいタグを1件追加する（既存タグは維持したまま追記する）
        """
        shop_domain = self.shop_url
        base = shop_domain if shop_domain.startswith("http") else f"https://{shop_domain}"
        order_url = f"{base}/admin/api/{self.api_version}/orders/{order_id}.json"

        async with httpx.AsyncClient(timeout=20.0) as client:
            r_get = await client.get(order_url, headers=self._headers(), params={"fields": "id,tags"})
            if r_get.status_code != 200:
                raise Exception(f"Failed to fetch order {order_id} for tagging: {r_get.status_code} - {r_get.text}")

            current_tags = [t.strip() for t in (r_get.json().get("order", {}).get("tags", "") or "").split(",") if t.strip()]
            if tag in current_tags:
                return
            current_tags.append(tag)

            r_put = await client.put(
                order_url,
                headers=self._headers(),
                json={"order": {"id": order_id, "tags": ", ".join(current_tags)}},
            )
            if r_put.status_code != 200:
                raise Exception(f"Failed to tag order {order_id}: {r_put.status_code} - {r_put.text}")

    async def get_order_by_name(self, name: str) -> dict | None:
        """
        注文名（Shopifyの注文番号表記, 例: "#P33986"）から該当注文を1件取得する。
        見つからない場合は None を返す。
        """
        params = {"name": name, "status": "any"}

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(self._orders_url(), headers=self._headers(), params=params)
            if response.status_code != 200:
                raise Exception(f"Failed to fetch order '{name}' from Shopify ({self.shop_url}): {response.status_code} - {response.text}")

            orders = response.json().get("orders", [])
            return orders[0] if orders else None

    def extract_recipient(self, order: dict) -> dict:
        """
        Shopify注文からお届け先情報（氏名・郵便番号・住所・電話番号）を抽出する。
        map_order_to_yamato_request() と 処理状況一覧のShopify注文キャッシュ の両方から使う。
        """
        shipping_address = order.get("shipping_address") or order.get("billing_address") or {}

        # 都道府県の日本語マッピング処理
        province_code = shipping_address.get("province_code") or ""
        province = ""

        # 1. province_code (JP-14など) からマッピング
        if province_code.startswith("JP-"):
            code = province_code.split("-")[1]
            province = PROVINCE_MAP.get(code, "")

        # 2. マッピングできなかった場合、provinceの英語名からマッピング
        if not province:
            prov_raw = shipping_address.get("province") or ""
            # すでに日本語ならそのまま使う
            if any(ord(c) > 127 for c in prov_raw):
                province = prov_raw
            else:
                province = EN_PROVINCE_MAP.get(prov_raw.lower(), prov_raw)

        city = shipping_address.get("city") or ""
        address1 = shipping_address.get("address1") or ""
        address2 = shipping_address.get("address2") or ""

        # お届け先住所（都道府県〜番地まで）。ヤマトAPIのconsignee_addressは全角32文字までのため、
        # 建物名(address2)は結合せずconsignee_address4として別送りする（extract_recipientのaddress2キー）。
        recipient_address = f"{province}{city}{address1}".strip()

        # 郵便番号のハイフン削除
        zip_code = shipping_address.get("zip") or ""
        recipient_zip = zip_code.replace("-", "").strip()

        # 氏名: Shopifyの name は "名 姓"（first_name + last_name）の順で連結されており、
        # 日本の配送慣習（姓 名）とは逆になっている。first_name/last_nameがあれば並べ替える。
        first_name = shipping_address.get("first_name") or ""
        last_name = shipping_address.get("last_name") or ""
        if first_name or last_name:
            recipient_name = f"{last_name} {first_name}".strip()
        else:
            recipient_name = shipping_address.get("name") or ""

        return {
            "name":    recipient_name,
            "zip":     recipient_zip,
            "address": recipient_address,
            "address2": address2,
            "phone":   clean_phone(shipping_address.get("phone") or ""),
        }

    def map_order_to_yamato_request(self, order: dict) -> ShipmentRequest:
        """
        Shopifyの注文情報をヤマトのShipmentRequestモデルにマッピングする
        """
        recipient = self.extract_recipient(order)

        # 品名の決定 (Line Items of the first item)
        line_items = order.get("line_items") or []
        item_name = ""
        if line_items:
            item_name = line_items[0].get("title", line_items[0].get("name", "商品"))
            # 2品以上ある場合は「外」を付与
            if len(line_items) > 1:
                item_name = f"{item_name[:20]}外"
            else:
                item_name = item_name[:25]
        else:
            item_name = "印刷商品"

        # ご依頼主（送り主）の情報のデフォルト値
        # （実際の値は基本的に store_settings で店舗ごとに上書きされる。 db.get_store_settings() 参照）
        sender_name = "株式会社PHOTOPRI"
        sender_zip = "173-0004"
        sender_address = "東京都板橋区板橋１丁目９−１０"
        sender_address2 = "3F"
        sender_phone = "070-9296-0635"

        # 送り状種類（ネコポス/コレクト(代金引換)/発払い）は注文タグから判定
        service_type = db.classify_yamato_service_type(order.get("tags", ""))
        amount = "0"
        tax_amount = ""
        if service_type == "2":  # コレクト（代金引換）: 実際に代金引換で徴収する金額を設定する
            amount = str(order.get("total_price") or "0").split(".")[0]
            tax_amount = str(order.get("total_tax") or "").split(".")[0]

        return ShipmentRequest(
            customer_order_no=str(order.get("order_number") or order.get("id")),
            service_type=service_type,
            amount=amount,
            tax_amount=tax_amount,
            ship_date="",  # 空白の場合、yamato_client側で本日日付を自動設定
            sender_name=sender_name,
            sender_zip=sender_zip,
            sender_address=sender_address,
            sender_address2=sender_address2,
            sender_phone=sender_phone,
            recipient_name=recipient["name"],
            recipient_zip=recipient["zip"],
            recipient_address=recipient["address"],
            recipient_address2=recipient["address2"],
            recipient_phone=recipient["phone"],
            item_name=item_name,
            total_count=1,
            weight_kg=1.0
        )

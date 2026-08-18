"""
郵便番号から住所（都道府県・市区町村）を引く、無料の公開API（zipcloud）との連携。

Shopifyの配送先住所とこの結果を突き合わせ、食い違いがあればスマホ画面で警告するために使う。
外部通信のため、失敗・タイムアウト時は None を返し、呼び出し側は照合をスキップして
通常通り処理を続行する（この照合のために送り状発行のスピードを落とさないため）。
"""
import httpx

ZIPCLOUD_URL = "https://zipcloud.ibsnet.co.jp/api/search"


async def lookup_address_by_zip(zip_code: str, timeout: float = 3.0) -> dict | None:
    """
    郵便番号（ハイフンあり/なしどちらでも可）から都道府県・市区町村を取得する。
    見つからない場合・通信エラー・タイムアウトの場合は None を返す。
    """
    digits = (zip_code or "").replace("-", "").strip()
    if len(digits) != 7 or not digits.isdigit():
        return None

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(ZIPCLOUD_URL, params={"zipcode": digits})
        if response.status_code != 200:
            return None
        data = response.json()
        results = data.get("results")
        if not results:
            return None
        result = results[0]
        return {
            "province": result.get("address1", ""),
            "city": result.get("address2", ""),
        }
    except Exception:
        return None

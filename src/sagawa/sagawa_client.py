"""
佐川急便 スマートAPI送り状（プラットフォーマー向け送り状発行API）連携。

「即時発行API」（sokuji）を使用する。送り状発行API（送り状発行API＋ファイル存在確認APIの
非同期ポーリング構成）とは異なり、1回のリクエストでPDFダウンロードURLが返るため、
ヤマトAPIと同様にスキャン→発行→印刷を1リクエストの流れで完結できる。

認証はセッションではなく、リクエストのたびに customerId + loginPassword を本文に含める。

仕様書: docs/sagawa/プラットフォーマー向け送り状発行API_API仕様書_Ver1.10.md
      （4.2. 即時発行API I/F、5.1 パラメータコード定義、5.2 処理結果コード）
"""
import os

from dotenv import load_dotenv

load_dotenv(os.getenv("APP_ENV_FILE", ".env"), override=True)

BASE_URL       = os.getenv("SAGAWA_API_BASE_URL", "https://smart-api-shipping.sagawa-exp.co.jp")
CUSTOMER_ID    = os.getenv("SAGAWA_CUSTOMER_ID", "")
LOGIN_PASSWORD = os.getenv("SAGAWA_LOGIN_PASSWORD", "")
KOKYAKU_CODE   = os.getenv("SAGAWA_KOKYAKU_CODE", "")
OKURI_CODE     = os.getenv("SAGAWA_OKURI_CODE", "A501")

# 5.2. 処理結果コード一覧（よく発生しうるものを中心に抜粋。未掲載コードはコードそのものを表示する）
RESULT_CODE_MESSAGES = {
    "E1-0001": "必須項目に値がありません",
    "E1-0002": "管理番号が重複しています",
    "E1-0003": "未登録の顧客コードです",
    "E1-0004": "個口数が正しくありません",
    "E1-0005": "便種コードが正しくありません",
    "E1-0007": "対象の顧客コードは代引契約をしていません",
    "E1-0013": "代金引換が正しくありません",
    "E1-0015": "依頼主住所１～３で文字数をオーバーしています",
    "E1-0016": "依頼主氏名１～２で文字数をオーバーしています",
    "E1-0017": "依頼主住所１に値がありません",
    "E1-0018": "依頼主氏名１に値がありません",
    "E1-0019": "お届け先住所１に値がありません",
    "E1-0020": "お届け先氏名１に値がありません",
    "E1-0022": "フラグの値が正しくありません",
    "E1-0027": "元着コードが正しくありません",
    "E1-0038": "届先郵便番号が正しい値ではありません（半角数字7桁・ハイフンなし）",
    "E1-0039": "依頼主郵便番号が正しい値ではありません（半角数字7桁・ハイフンなし）",
    "E1-0040": "届先電話番号が正しい値ではありません",
    "E1-0041": "依頼主電話番号が正しい値ではありません",
    "E1-0042": "お届先住所１～３で文字数をオーバーしています",
    "E1-0043": "お届先氏名１～２で文字数をオーバーしています",
    "E1-0047": "送り状コードが正しくありません",
    "E1-0048": "出力レベルが正しくありません",
    "E1-0049": "管理番号が正しくありません",
    "E1-0050": "顧客コードが正しくありません",
    "E1-0053": "代引消費税が正しくありません",
    "E1-0064": "配送会社コードが正しくありません",
    "E2-0001": "郵便番号と住所が正しくありません",
    "E2-0002": "郵便番号から該当する住所はありません",
    "E2-0003": "住所から該当する郵便番号はありません",
    "E2-0004": "お届け先の郵便番号と住所が一致していません",
    "E2-0005": "依頼主の郵便番号と住所が一致していません",
    "E2-0007": "代金引換不可エリアです",
    "E3-0001": "アカウント認証が正しくありません（カスタマID・ログインパスワードを確認してください）",
    "E8-0001": "エラー有り",
    "E9-0001": "システムエラーです（佐川急便のサポートへお問い合わせください）",
}


def format_sagawa_error(result: dict) -> str:
    """issue_sagawa_pdf() の失敗結果を、担当者が読んで対処できる形式のメッセージに整形する"""
    step = result.get("step", "")
    if step == "sokuji_check":
        codes = result.get("errors") or ([result["result_code"]] if result.get("result_code") else [])
        if codes:
            lines = [f"・{c}: {RESULT_CODE_MESSAGES.get(c, '不明なエラー')}" for c in codes]
            return "送り状データの入力内容にエラーがあります（Shopify注文の住所等を確認・修正のうえ再試行してください）:\n" + "\n".join(lines)
        return "送り状データにエラーがありますが、詳細を取得できませんでした。"
    if step == "sokuji":
        return f"佐川APIへの送信に失敗しました（HTTP {result.get('status')}）: {result.get('body', '')[:300]}"
    if step == "sokuji_no_url":
        return "佐川APIから送り状PDFのダウンロードURLを取得できませんでした。"
    if step == "download":
        return f"送り状PDFのダウンロードに失敗しました（HTTP {result.get('status')}）: {result.get('body', '')[:300]}"
    return str(result)


async def issue_sagawa_pdf(client, store_name: str, order_no: str, sagawa_req: dict, output_dir: str) -> tuple[bool, dict]:
    """佐川急便 即時発行API（sokuji）で送り状を発行し、PDFを出力フォルダへ保存する"""
    print_data_detail = {
        "haisoKosu": "1",
        "userManageNumber": sagawa_req["user_manage_number"],
        "kokyakuCode": KOKYAKU_CODE,
        "otodokeAdd1": sagawa_req["recipient_address1"],
        "otodokeAdd2": sagawa_req["recipient_address2"],
        "otodokeAdd3": sagawa_req["recipient_address3"],
        "otodokeNm1": sagawa_req["recipient_name"],
        "otodokeNm2": "",
        "otodokeYubin": sagawa_req["recipient_zip"],
        "otodokeTel": sagawa_req["recipient_phone"],
        "otodokeMailAddress": "",
        # 依頼主指定フラグ=1: 顧客コードに紐づく出荷場情報ではなく、下記の依頼主情報を印字する
        # （ブランドごとに依頼主表示を変えるための必須設定。ヤマトの sender_* と同じ役割）
        "iraiPrintFlg": "1",
        "iraiAdd1": sagawa_req["sender_address1"],
        "iraiAdd2": sagawa_req["sender_address2"],
        "iraiAdd3": "",
        "iraiNm1": sagawa_req["sender_name"],
        "iraiNm2": "",
        "iraiYubin": sagawa_req["sender_zip"].replace("-", ""),
        "iraiTel": sagawa_req["sender_phone"],
        "iraiMailAddress": "",
        "shippingDate": "",
        "kiji1": sagawa_req["item_name"],
        "kiji2": "", "kiji3": "", "kiji4": "", "kiji5": "", "kiji6": "",
        "binsyuCode": "000",  # 陸便
        "daibikiFlg": "1" if sagawa_req["is_cod"] else "0",
        "daibikiType": "",
        # 配達指定日は空欄にし、佐川側の標準（最短）でお届けする
        "shiteiDate": "",
        "shiteiTimeCode": "",
        "daibikiKingaku": sagawa_req["cod_amount"] if sagawa_req["is_cod"] else "",
        "daibikiTax": sagawa_req["cod_tax"] if sagawa_req["is_cod"] else "",
        "weight1": "", "weight2": "",
        "careSeal1": "", "careSeal2": "", "careSeal3": "",
        "hokenKingaku": "",
        "eidomeFlg": "",
        "depotCode": "",
        "mark": "",
        "motoChakuCode": "0",  # 元払い
    }

    payload = {
        "customerAuth": {
            "customerId": CUSTOMER_ID,
            "loginPassword": LOGIN_PASSWORD,
        },
        "deliveryCode": "0001",
        "printOutFlg": "1",  # 発行依頼機能（実際に送り状PDFを作成する）
        "okuriCode": OKURI_CODE,
        "outputLevel": "000",
        "backLayerFlg": "1",
        "printDataList": {"printDataDetail": [print_data_detail]},
    }

    print(f"\n[{order_no}] 佐川API送信データ:")
    print(f"  お届け先: {print_data_detail['otodokeNm1']} / 〒{print_data_detail['otodokeYubin']} "
          f"{print_data_detail['otodokeAdd1']}{print_data_detail['otodokeAdd2']} / {print_data_detail['otodokeTel']}")

    r = await client.post(
        f"{BASE_URL}/api/sokuji/json",
        headers={"Content-Type": "application/json"},
        json=payload,
    )
    if r.status_code != 200:
        return False, {"step": "sokuji", "status": r.status_code, "body": r.text[:500]}

    data = r.json()
    result_code = data.get("resultCode", "")

    if not (result_code.startswith("S") or result_code.startswith("W")):
        detail_list = data.get("printDataList", {}).get("printDataDetail", [])
        errors = detail_list[0].get("resultCodeList", {}).get("resultCode", []) if detail_list else []
        return False, {"step": "sokuji_check", "result_code": result_code, "errors": errors}

    pdf_url = data.get("url", "")
    if not pdf_url:
        return False, {"step": "sokuji_no_url", "body": data}

    r2 = await client.get(pdf_url, timeout=60.0)
    if r2.status_code != 200 or len(r2.content) <= 100:
        return False, {"step": "download", "status": r2.status_code, "body": r2.text[:200]}

    os.makedirs(output_dir, exist_ok=True)
    pdf_filename = f"scan_{store_name}_{order_no}_sagawa.pdf"
    pdf_path = os.path.join(output_dir, pdf_filename)
    with open(pdf_path, "wb") as f:
        f.write(r2.content)

    tracking_number = ""
    detail_list = data.get("printDataList", {}).get("printDataDetail", [])
    if detail_list:
        numbers = detail_list[0].get("shippingNumberList", {}).get("shippingNumber", [])
        tracking_number = numbers[0] if numbers else ""

    return True, {
        "tracking_number": tracking_number,
        "pdf_path": pdf_path,
    }

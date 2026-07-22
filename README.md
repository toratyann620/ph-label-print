# 送り状自動作成システム - README

ヤマト運輸・佐川急便のAPIを活用した、Shopify注文連携の送り状自動作成システムです。

---

## プロジェクト構成

```
.
├── .env                     # 環境変数設定（認証情報）
├── requirements.txt         # Python依存パッケージ
├── docs/                    # 仕様書・マニュアル
│   ├── yamato/              # ヤマト運輸関連ドキュメント
│   │   ├── api_spec.md                        # B2クラウドAPI仕様 (送り状発行)
│   │   ├── yamato_tracking_api_spec.md        # 荷物問い合わせAPI仕様 (配送追跡)
│   │   ├── 【B2クラウド】仕様書（APIデータ交換規約4.7版）.pdf
│   │   └── 20231205_お荷物問い合わせ API連携マニュアル.pdf
│   └── sagawa/              # 佐川急便関連ドキュメント（準備中）
├── src/                     # ソースコード
│   ├── yamato/              # ヤマト運輸API連携
│   │   ├── yamato_client.py       # B2クラウドAPIクライアント
│   │   ├── issue_slip.py          # 仮データで送り状発行（単体テスト用）
│   │   └── issue_slip_shopify.py  # Shopify注文連携で送り状発行
│   ├── sagawa/              # 佐川急便API連携（準備中）
│   ├── shopify/             # Shopify API連携
│   │   └── shopify_client.py      # Shopify注文取得クライアント
│   └── common/              # 共通モジュール
│       ├── app.py                 # FastAPI アプリケーション
│       └── models.py              # データモデル（Pydantic）
├── output/                  # 生成された送り状PDF
├── logs/                    # 処理ログ（API送信履歴など）
└── templates/               # HTMLテンプレート
```

---

## 環境構築

```bash
# Python仮想環境の作成と有効化
python3.13 -m venv .venv
source .venv/bin/activate

# 依存パッケージのインストール
pip install -r requirements.txt
```

---

## 使い方

### Shopify注文から送り状を発行（ヤマト運輸）

```bash
# プロジェクトルートから実行
python3.13 src/yamato/issue_slip_shopify.py
```

* `PHOTOPRI` ストアの最新3件の注文情報をShopify APIから取得します。
* ヤマト運輸B2クラウドAPIを呼び出し、送り状PDFを生成します。
* 生成されたPDFは `output/` フォルダに保存されます。
* API送信ログは `logs/yamato_last_requests.json` に保存されます。

### 仮データで送り状を発行（単体テスト用）

```bash
python3.13 src/yamato/issue_slip.py
```

---

## 対応サービス

| 運送会社 | 送り状発行 | 配送追跡 | 状態 |
|---------|---------|---------|-----|
| ヤマト運輸 | ✅ B2クラウドAPI | ✅ 荷物問い合わせAPI | 検証環境で動作確認済み |
| 佐川急便 | 🔜 準備中 | — | — |

---

## 環境変数（.env）

```env
# ヤマト運輸 B2クラウドAPI（送り状発行）
YAMATO_API_BASE_URL=https://testb2api.kuronekoyamato.co.jp  # 検証環境
# YAMATO_API_BASE_URL=https://newb2web.kuronekoyamato.co.jp # 本番環境
YAMATO_CUSTOMER_CODE=...
YAMATO_API_KEY=...
YAMATO_INVOICE_CODE=...
YAMATO_INVOICE_CODE_EXT=...
YAMATO_INVOICE_FREIGHT_NO=01

# Shopify API
SHOPIFY_PHOTOPRI_SHOP=photopri.myshopify.com
SHOPIFY_PHOTOPRI_TOKEN=...
...
SHOPIFY_API_VERSION=2024-04
```

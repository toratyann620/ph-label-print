# CLAUDE.md — Shopify連携 ヤマト・佐川送り状自動作成システム

本ドキュメントは、Claude Code が本プロジェクトの開発を引き継ぎ、スムーズにコマンド実行や実装を進めるための概要・ステータス・操作マニュアルです。

---

## 1. プロジェクト概要

Shopifyで運営されているECストア（PHOTOPRI、ARTGRAPH、E1、QOOなど）の注文情報をAPI経由で取得し、ヤマト運輸（B2クラウドAPI）および佐川急便（お荷物問い合わせAPI）と連携して、送り状の自動発行（PDF取得）および配送状況追跡を行うPythonベースのシステムです。

### 構成要素
- **Shopify API 連携部**: 各ストアの注文情報を取得し、共通配送モデルにマッピング。
- **ヤマト B2クラウド API 連携部**: サーバー間連携（画面API利用なし）で出荷登録からPDFダウンロード、伝票番号取得までを完全自動化。
- **佐川急便 連携部**: 配送状況追跡（お荷物問い合わせAPI）およびe-飛伝用CSVエクスポート設計（※保留中）。
- **FastAPI サーバー**: Webhooksの受信や手動実行用のAPIエンドポイント（ポート `3131`）を提供。

---

## 2. ディレクトリ・ファイル構成

```text
/Users/kurokawamutsuo/開発フォルダ/036_【PH】ヤマト送り状自動作成/
├── CLAUDE.md                 # 本ドキュメント（引き継ぎ用）
├── .env                      # 認証情報・環境設定（本番/検証切り替え）
├── README.md                 # 基本的な利用ガイド
├── requirements.txt          # 依存パッケージ
├── docs/                     # 仕様書・ドキュメント類
│   ├── yamato/
│   │   ├── api_spec.md       # ヤマトB2クラウドAPI仕様まとめ
│   │   └── 【B2クラウド】仕様書（APIデータ交換規約4.7版）.pdf
│   └── sagawa/
│       ├── sagawa_api_spec.md # 佐川お荷物問い合わせAPI仕様まとめ（PDFからMarkdown化）
│       └── API連携マニュアル.pdf
├── src/                      # ソースコード
│   ├── common/
│   │   ├── app.py            # FastAPIサーバー（ポート: 3131）
│   │   └── models.py         # Pydanticデータモデル（共通リクエスト/レスポンス）
│   ├── shopify/
│   │   └── shopify_client.py # Shopify注文取得・住所日本語化・モデルマッピング
│   ├── yamato/
│   │   ├── yamato_client.py  # ヤマトAPIクライアント（editA -> new -> polling -> getfile）
│   │   ├── issue_slip.py     # 送り状発行メイン
│   │   └── issue_slip_shopify.py # Shopify注文と連携したヤマト送り状発行
│   └── sagawa/               # 空（※保留中）
└── logs/
    └── yamato_last_requests.json # ヤマトAPIへの最終送信リクエスト/レスポンスログ
```

---

## 3. コマンド・実行マニュアル

Claude Code が開発・検証時に実行する主要なコマンドです。

### ① 仮想環境と依存関係のインストール
```bash
# プロジェクトルートにて
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### ② Shopify連携ヤマト送り状発行テストの実行
Shopifyから最新の注文を1件取得し、ヤマトAPIへ送信してPDFをダウンロードするテストです。
※パスを通すために `PYTHONPATH` を指定して実行します。
```bash
PYTHONPATH=src/shopify:src/common .venv/bin/python src/yamato/issue_slip_shopify.py
```

### ③ APIサーバー（FastAPI）の起動
ポート台帳に登録されている専用ポート **`3131`** を使用して起動します。
```bash
.venv/bin/uvicorn src.common.app:app --host 0.0.0.0 --port 3131 --reload
```

---

## 4. これまで実行したこと

1. **ヤマト連携（検証環境）の動作完了**
   - Shopifyから注文（英語表記の都道府県や、国際表記 `+81` の電話番号など）を自動取得し、ヤマト仕様にクレンジングして登録する処理を実装。
   - 検証環境（`testb2api.kuronekoyamato.co.jp`）において、PDFダウンロードおよび伝票番号の確定・取得までの一連の疎通テストを成功させました。
2. **ポート台帳（`04_PORT_MANAGEMENT.md`）の更新**
   - 本プロジェクトのローカルポートを **`3131`** に固定し、台帳に追記。`app.py` のデフォルトポートも `3131` に変更済み。
3. **佐川連携のドキュメント化**
   - ユーザーから提供された `API連携マニュアル.pdf` を解析。中身は「お荷物問い合わせAPI（追跡）」のみであり、送り状発行機能は含まれていないことを確認。仕様を `docs/sagawa/sagawa_api_spec.md` にMarkdown化。佐川連携の実装自体は現在保留中。
4. **ヤマト本番環境への接続先切り替え**
   - `.env` ファイルに本番環境URL `https://newb2web.kuronekoyamato.co.jp` を適用し、本番キー入力用の枠を用意。

---

## 5. 現状のステータスと次の課題

### 🔴 【現在のアラート】ヤマト本番環境で HTTP 401（認証エラー）が発生中
- **現状**: `.env` 内の本番用設定（`YAMATO_API_BASE_URL`）は本番環境URLに変更されましたが、認証キー（`YAMATO_API_KEY`）や会社コード（`YAMATO_CUSTOMER_CODE`）に検証環境（テスト用）のデモキーが設定されたままになっているため、本番サーバーから `HTTP 401 Authentication error` で接続を拒否されています。
- **課題**: ユーザーから「ヤマトビジネスメンバーズ」の本番環境で発行された**正しい本番用認証情報**を受け取り、`.env` に反映させる必要があります。

### 🟡 佐川急便連携の保留状態
- **現状**: 佐川急便のAPIに関しては、送り状発行APIの仕様書がないため保留となっています。
- **課題**: 今後進める場合は、ユーザーから佐川急便の「スマートAPI（送り状発行API）仕様書」を入手してもらうか、e-飛伝用のCSVエクスポート機能を実装する必要があります。

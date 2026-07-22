# B2クラウド APIデータ交換規約 4.7版 — 仕様まとめ

> 原典: 【B2クラウド】仕様書（APIデータ交換規約4.7版）.pdf  
> 作成: 2026-06-15

---

## 目次

1. [インターフェース概要](#1-インターフェース概要)
2. [ユーザー操作フロー](#2-ユーザー操作フロー)
3. [API連携利用パターン](#3-api連携利用パターン)
4. [認証について](#4-認証について)
5. [通信プロトコル](#5-通信プロトコル)
6. [利用可能API一覧](#6-利用可能api一覧)
7. [APIインターフェース詳細](#7-apiインターフェース詳細)
8. [HTTPステータスについて](#8-httpステータスについて)
9. [出荷データ仕様（主要項目）](#9-出荷データ仕様主要項目)
10. [制限事項](#10-制限事項)
11. [API検証環境FAQ](#11-api検証環境faq)

---

## 1. インターフェース概要

お客様システムからヤマト運輸のB2クラウドシステムにREST/ATOM形式でアクセスし、シームレスに送り状を発行するAPIです。

### 扱える伝票種別

| コード | 種別 |
|--------|------|
| 0 | 発払い |
| 2 | コレクト |
| 3 | クロネコゆうメール |
| 4 | タイム |
| 5 | 着払い |
| 6 | 発払い（複数口） |
| 7 | クロネコゆうパケット |
| 8 | 宅急便コンパクト |
| 9 | コンパクトコレクト |
| A | ネコポス |

### ご利用パターン

| パターン | 説明 |
|----------|------|
| ①画面API利用あり | お客様システムで入力した情報をB2クラウド画面で表示・修正後に発行 |
| ②画面API利用なし | お客様システムとB2クラウド間でデータのやり取りをし、全操作をお客様システム側で実施 |

---

## 2. ユーザー操作フロー

### 前提条件

1. ヤマト運輸との未収取引契約を締結済み
2. ヤマトビジネスメンバーズの本登録が完了していること
3. **APIアクセス認証キー**はヤマトビジネスメンバーズの管理者ユーザーのみ確認可能
4. **API連携会社コード** はお客様契約時にB2クラウドシステム担当より発行 → URLパラメータ `api_user_id` に設定
5. **許可ドメイン登録** — B2クラウドにアクセスするドメインを事前登録（クロスサイトアクセスのため）
6. **PDF有効期間の登録**（画面API利用なしの場合）— 1〜24時間（検証環境では有効時間なし）

> ⚠️ **検証環境では**、リリース完了通知メールに記載の認証キーをそのまま使用してください。

---

## 3. API連携利用パターン

### パターン①：画面API利用あり（ブラウザ連携）

```
[お客様システム]
  │ POST /b2/p/editA?api_user_id=XXXCD   ← Authorization: Token {Accesstoken}
  │ Body: 出荷データ（JSON）
  ▼
[B2クラウド] → RXID①を返却
  │
  │ GET https://newb2web.kuronekoyamato.co.jp/b2/p/_html/multi_import_api.html
  │         ?notify=https://xxx.co.jp/xxx&_RXID={RXID①}
  ▼
[B2クラウド画面（ブラウザ）] → 送り状発行
  │ B2から通知先URLへ GET https://xxx.co.jp/xxx?_RXID={RXID②}
  ▼
[お客様システム]
  │ GET /b2/p/editA?spool&_RXID={RXID②}
  ▼
  伝票番号取得
```

### パターン②：画面API利用なし（サーバー間連携）

```
[お客様システム]
  │ 1. POST /b2/p/editA?api_user_id=XXXCD   ← Authorization: Token {Accesstoken}
  │    Body: 出荷データ（JSON）
  │    → 出荷データチェック済みデータ + updated + tracking_number(仮) を受け取る
  │
  │ 2. POST /b2/p/new?issue_editA&display=0&print_type=m
  │    Body: {feed:{entry:[{id,shipment:{tracking_number,created_ms,service_type,shipment_flg:"1"}}]}}
  │    → 発行番号(issue_no)を受け取る
  │
  │ 3. GET /b2/p/polling?issue_no=xxx&display=0
  │    → 200: 作成完了 / 202: 作成中 / 400: エラー
  │    (完了まで繰り返す)
  │
  │ 4. GET /b2/p/getfile?display=0&issue_no=xxx&checkonly=1
  │    → 印刷データの存在チェック
  │
  │ 5. GET /b2/p/getfile?display=0&issue_no=xxx&fileonly=1
  │    → PDF取得（バイナリ）
  │
  │ 6. GET /b2/p/editA?spool&_RXID={印刷状態確認のRXID}
  │    → 伝票番号が付与された出荷データ取得
  ▼
  完了
```

---

## 4. 認証について

### 認証方法

**最初のリクエスト**のみ HTTPリクエストヘッダーにAccesstokenを設定します。

```
Authorization: Token {Accesstoken}
```

> ⚠️ `Token` の後ろに**半角スペース**が必要です

- `{Accesstoken}` にはB2クラウドで表示される **APIアクセス認証キー** をそのままセットします
- **検証環境の場合**: 検証環境リリース完了通知メールに記載の認証キーを使用
- 認証後はCookieにセッションIDが設定され、以降はセッションIDで認証されます
- **2回目以降のリクエストでは Authorizationヘッダーを設定しないでください**

### 検証環境 認証情報

| 項目 | 値 |
|------|----|
| API連携会社コード (api_user_id) | `.env` の `YAMATO_CUSTOMER_CODE` |
| Accesstoken (認証キー) | `.env` の `YAMATO_API_KEY` |
| 検証環境URL | `https://testb2api.kuronekoyamato.co.jp` |

### ヘッダー設定例

```http
POST /b2/p/editA?api_user_id=HFewpGYA3MKGAqzQArsr HTTP/1.1
Host: testb2api.kuronekoyamato.co.jp
Authorization: Token @900000000211-999,PkJXM+vZ8pYwoRBjNKV47A41NlgPuE/WQvot+EohyRo=
Content-Type: application/json
```

---

## 5. 通信プロトコル

### データ構造

- フォーマット: **JSON** または MessagePack
- 文字コード: **UTF-8**
- ATOM形式（RFC4287）の概念に基づく: `feed > entry[] > shipment`

```json
{
  "feed": {
    "entry": [
      {
        "id": "1",
        "shipment": { ... },
        "link": [{"___href": "1", "___rel": "self"}]
      }
    ]
  }
}
```

### REST操作

| メソッド | 成功時ステータス | ボディ |
|----------|-----------------|--------|
| GET | 200 | 応答データ |
| POST | 200 | なし、または応答データ |
| PUT | 200 | 応答データ |

### 排他制御

- `PUT`, `POST`（仮データ更新・削除・送り状発行）では `feed.updated` に前回レスポンスの `updated` 値を設定
- B2クラウド側のRevisionと比較し、古い場合は **HTTP 409** を返却
- 排他エラーの場合は「仮データ取得API」で最新データを取得してから再送

---

## 6. 利用可能API一覧

### 画面API利用なし の場合（本プロジェクトのメインパターン）

| API名 | メソッド | エンドポイント | 説明 |
|-------|---------|---------------|------|
| 仮データ登録・データチェック | POST | `/b2/p/editA?api_user_id=XXXCD` | 出荷データを登録しチェック |
| 仮データ取得 | GET | `/b2/p/editA` | 未発行の出荷データを取得 |
| 仮データ更新・データチェック | PUT | `/b2/p/editA` | 出荷データの更新とチェック |
| 仮データ削除 | POST | `/b2/p/editA` | 出荷データの削除 |
| 送り状発行 | POST | `/b2/p/new?issue_editA` | 伝票番号採番・印刷データ作成開始 |
| 印刷状態確認 | GET | `/b2/p/polling?issue_no=xxx&display=0` | 印刷データ作成状況の確認 |
| 印刷データチェック | GET | `/b2/p/getfile?display=0&issue_no=xxx&checkonly=1` | PDFの存在チェック |
| PDFダウンロード | GET | `/b2/p/getfile?display=0&issue_no=xxx&fileonly=1` | PDF取得 |
| 伝票番号取得 | GET | `/b2/p/editA?spool&_RXID=xxx` | 発行済み出荷データ取得 |

---

## 7. APIインターフェース詳細

### 7-1. 仮データ登録・データチェック

```
POST /b2/p/editA?api_user_id={API連携会社コード}
```

**リクエストヘッダー**

| ヘッダー | 必須 | 値 |
|---------|------|----|
| Content-Type | ○ | `application/json` |
| Authorization | ○ | `Token {Accesstoken}` ← **最初のリクエストのみ** |

**レスポンス**

- 成功: HTTP 200、チェック済み出荷データ
- `feed.title` に RXID が設定される
- API連携会社コードが誤り: HTTP 403、`feed.summary` = `api_use_id[xxx] was not avirable.`

**重要**: 出荷データにエラーがある場合でもHTTP 200を返します。エラー情報は `entry[].error` に含まれます。

---

### 7-2. 仮データ取得

```
GET /b2/p/editA
```

**リクエストヘッダー**: Authorization不要（セッションIDで認証）

**レスポンス**: HTTP 200、未発行出荷データ一覧

---

### 7-3. 仮データ更新・データチェック

```
PUT /b2/p/editA
```

**リクエストヘッダー**

| ヘッダー | 必須 | 値 |
|---------|------|----|
| X-Requested-With | ○ | `XMLHttpRequest`（CSRF対策） |
| Content-Type | ○ | `application/json` |

**リクエストボディ**: 前回レスポンスの `tracking_number` と `created_ms` を必ずセット

---

### 7-4. 送り状発行

```
POST /b2/p/new?issue_editA&display=0&print_type=m
```

**URLパラメータ**

| パラメータ | 必須 | 値 | 説明 |
|-----------|------|----|------|
| display | ○ | `0` | 固定値（画面なし） |
| print_type | ○ | `m` | A4マルチ印刷 / `m5` = A5 / `0` = 発払い(サーマル) 等 |

**リクエストヘッダー**

| ヘッダー | 必須 | 値 |
|---------|------|----|
| X-Requested-With | ○ | `XMLHttpRequest` |
| Content-Type | ○ | `application/json` |

**リクエストボディ（必須項目）**

```json
{
  "feed": {
    "updated": "1736328400684",
    "entry": [
      {
        "id": "1",
        "shipment": {
          "tracking_number": "1",
          "created_ms": "1736328400682",
          "service_type": "0",
          "printer_type": "1",
          "shipment_flg": "1"
        }
      }
    ]
  }
}
```

**レスポンス（成功）**

```json
{
  "feed": {
    "title": "TMIN0000001638",
    "subtitle": "428",
    "updated": "1494823394373"
  }
}
```

- `feed.title` = 発行番号（polling時の `issue_no` に使用）
- `feed.subtitle` = 帳票生成想定時間（ミリ秒）

---

### 7-5. 印刷状態確認

```
GET /b2/p/polling?issue_no={発行番号}&display=0
```

| ステータスコード | 意味 |
|-----------------|------|
| 200 | 作成完了（`feed.title` にRXIDが設定） |
| 202 | 作成中（再ポーリング） |
| 400 | 作成失敗 |

**レスポンス例（完了時）**

```json
{
  "feed": {
    "title": "RXID...",
    "subtitle": "200",
    "entry": [{"summary": "created", "title": "Success", "subtitle": "200"}]
  }
}
```

---

### 7-6. PDFダウンロード

```
GET /b2/p/getfile?display=0&issue_no={発行番号}&fileonly=1
```

成功時: HTTP 200、PDFバイナリデータ

---

### 7-7. 伝票番号取得

```
GET /b2/p/editA?spool&_RXID={RXID}
```

- 印刷状態確認で完了（200）時の `feed.title`（RXID）をパラメータに使用
- レスポンスの `tracking_number` に実際の伝票番号が設定されます

---

## 8. HTTPステータスについて

| コード | 意味 |
|--------|------|
| 200 | 成功（業務エラーがあってもHTTP 200で返る場合あり） |
| 202 | 処理中（印刷状態確認時） |
| 400 | リクエストエラー・業務エラー |
| 401 | 認証エラー（`{"feed": {"title": "Authentication error."}}`) |
| 403 | API連携会社コードエラー |
| 409 | 排他エラー（Revisionが古い） |
| 416 | データ件数制限オーバー（最大1000件） |
| 417 | CSRF検証エラー（X-Requested-Withヘッダーなし） |
| 419 | ビジー状態 |
| 500 | サーバーエラー |

### エラーレスポンス形式

```json
{
  "feed": {
    "title": "Error",
    "subtitle": "403",
    "summary": "api_use_id[xxxCD] was not avirable."
  }
}
```

### 業務エラー（HTTP 200 で返却）

```json
{
  "feed": {
    "entry": [
      {
        "shipment": { ... },
        "error": [
          {
            "error_property_name": "invoice_code",
            "error_code": "ES006002",
            "error_description": "請求先が存在しません。"
          }
        ],
        "error_flg": "9"
      }
    ]
  }
}
```

- `error_flg`: `0`=正常、`1`=警告、`9`=エラー
- エラーコードが `E` で始まる = エラー、`W` で始まる = 警告

---

## 9. 出荷データ仕様（主要項目）

### 必須項目

| No | 項目名 | 物理名 | 桁数 | 説明 |
|----|--------|--------|------|------|
| 3 | 送り状種類 | service_type | 1 | 0:発払い 2:コレクト 3:ゆうメール 4:タイム 5:着払い 6:複数口 7:ゆうパケット 8:コンパクト 9:コンパクトコレクト A:ネコポス |
| 5 | 出荷予定日 | shipment_date | 8 | YYYYMMDD形式 |
| 10 | 請求先・顧客コード | invoice_code | 12 | クロネコゆうメール・着払い以外は必須 |
| 11 | 請求先・分類コード | invoice_code_ext | 3 | クロネコゆうメール・着払い以外は必須 |
| 12 | 請求先・運賃管理番号 | invoice_freight_no | 2 | クロネコゆうメール・着払い以外は必須 |
| 36 | お届け完了メール利用フラグ | is_using_delivery_email | 1 | 0:利用しない 1:利用する |
| 41 | ご依頼主・電話番号 | shipper_telephone_display | 15 | クロネコゆうメール以外は必須 |
| 43 | ご依頼主・名 | shipper_name | 32/16 | クロネコゆうメール以外は必須 |
| 45 | ご依頼主・郵便番号 | shipper_zip_code | 7 | クロネコゆうメール以外は必須（ハイフンあり/なし両可） |
| 55 | お届け先・名 | consignee_name | 32/16 | 全角、必須 |
| 56 | お届け先・郵便番号 | consignee_zip_code | 7 | 必須 |

### 主な任意項目

| No | 項目名 | 物理名 | 説明 |
|----|--------|--------|------|
| 1 | 伝票番号 | tracking_number | B2クラウドが付与。レスポンスに設定 |
| 2 | お客様管理番号 | shipment_number | 英数字+記号(_-) |
| 4 | クール区分 | is_cool | 0:通常 1:冷凍 2:冷蔵 |
| 6 | お届け予定日 | delivery_date | YYYYMMDD または "最短日" |
| 29 | 登録元システム種別 | input_system_type | 固定値 `"api"` |
| 39 | プリンタ種別 | printer_type | 1:レーザー 2:インクジェット 3:ラベル |
| 46 | ご依頼主・入力住所 | shipper_address | 都道府県〜番地まで |
| 50 | ご依頼主・建物名 | shipper_address4 | アパート名等 |
| 57 | お届け先・入力住所 | consignee_address | 都道府県〜番地まで |
| 61 | お届け先・建物名 | consignee_address4 | アパート名等 |
| 70 | 品名称1 | item_name1 | クロネコゆうメール以外は必須 |

---

## 10. 制限事項

| 項目 | 内容 |
|------|------|
| 登録件数 | 1回最大 **1000件** |
| メンテナンス時間 | 毎日 25:00〜7:00 |
| セッションID有効期間 | 最後の操作から **60分** |
| ワンタイムパスワード(RXID) | 発行後 **60分**、**1回限り** |
| 検証環境の発行伝票 | **サンプルPDF**（入力情報は反映されない） |
| 検証環境のサービスレベル | 固定で発地点が**北海道** |

---

## 11. API検証環境FAQ

公式FAQは以下を参照してください:  
[B2クラウドAPI よくあるご質問（ヤマトビジネスメンバーズ）](https://www.yamatobiz.co.jp/)

### よくある認証エラーの対処

1. `Authorization: Token {Accesstoken}` の形式を確認（`Token ` の後に**半角スペース**）
2. 検証環境用の認証キー（通知メール記載）を使用しているか確認
3. `api_user_id` パラメータに正しいAPI連携会社コードを設定しているか確認
4. 2回目以降のリクエストで `Authorization` ヘッダーを設定していないか確認

---

## 付録：リクエスト/レスポンスサンプル

### 仮データ登録リクエスト（1件）

```json
{
  "feed": {
    "entry": [
      {
        "shipment": {
          "shipment_number": "API_TEST1",
          "service_type": "0",
          "is_cool": "0",
          "shipment_date": "20250920",
          "delivery_date": "",
          "amount": "0",
          "tax_amount": "",
          "invoice_code": "100000000023",
          "invoice_code_ext": "999",
          "invoice_freight_no": "01",
          "invoice_name": "",
          "payment_flg": "0",
          "input_system_type": "api",
          "package_qty": "1",
          "delivery_time_zone": "",
          "is_using_shipment_email": "0",
          "is_using_delivery_email": "0",
          "shipper_telephone_display": "03-1234-5678",
          "shipper_name": "依頼主　名前",
          "shipper_zip_code": "1690072",
          "shipper_address": "東京都新宿区大久保１－２－３",
          "consignee_telephone_display": "06-9876-5432",
          "consignee_name": "お届け先　名前",
          "consignee_zip_code": "5300001",
          "consignee_address": "大阪府大阪市北区梅田１－１",
          "item_name1": "商品名",
          "is_using_shipment_post_email": "0",
          "is_using_cons_deli_post_email": "0",
          "is_using_shipper_deli_post_email": "0"
        }
      }
    ]
  }
}
```

### 仮データ登録レスポンス（成功例）

```json
{
  "feed": {
    "title": "RXID_文字列",
    "updated": "1736328400684",
    "entry": [
      {
        "shipment": {
          "tracking_number": "1",
          "created_ms": "1736328400682",
          "service_type": "0",
          ...
        },
        "id": "1",
        "link": [{"___href": "1", "___rel": "self"}]
      }
    ]
  }
}
```

### 送り状発行リクエスト

```json
{
  "feed": {
    "updated": "1736328400684",
    "entry": [
      {
        "id": "1",
        "shipment": {
          "tracking_number": "1",
          "created_ms": "1736328400682",
          "service_type": "0",
          "printer_type": "1",
          "shipment_flg": "1"
        }
      }
    ]
  }
}
```

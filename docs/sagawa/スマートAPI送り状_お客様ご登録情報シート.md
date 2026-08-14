# スマートAPI送り状 お客様ご登録情報シート

**記入日：2026年8月5日**
第1.1版　2025年7月28日
Copyright(C)SAGAWA EXPRESS CO.,LTD. All rights reserved.

---

## 本書について

### 概要

スマートAPI送り状のご利用を開始されるお客様に、SGシステム(以下、弊社)のスマートAPI送り状ご利用環境をご連携します。
お客様テスト環境をご利用頂いていた場合は、下記のスマートAPI送り状ご利用環境に設定の変更をお願いします。

### ご登録情報

| 項目 | 内容 |
|------|------|
| お客様 | 株式会社PHOTOPRI　様 |
| カスタマID | 12357473 |
| ログインパスワード | 別途メールにてご連絡いたします。 |
| 顧客コード(チェックデジット付) | 150509780001 |
| 送り状コード | 仕様書参照 |

---

## スマートAPI送り状お客様ご利用環境について

### XML形式でご利用の場合

| No. | API名称 | リクエストURL |
|-----|---------|----------------|
| 1 | 送り状発行API | https://smart-api-shipping.sagawa-exp.co.jp/api/shipping/xml |
| 2 | 即時発行API | https://smart-api-shipping.sagawa-exp.co.jp/api/sokuji/xml |
| 3 | ファイル存在確認API | https://smart-api-shipping.sagawa-exp.co.jp/api/checkfile/xml |
| 4 | 利用実績API | https://smart-api-shipping.sagawa-exp.co.jp/api/riyoujisseki/xml |
| 5 | 送り状再発行依頼API | https://smart-api-shipping.sagawa-exp.co.jp/api/retryprint/xml |
| 6 | 佐川急便マスタ参照API | https://smart-api-shipping.sagawa-exp.co.jp/api/checkaddress/xml |
| 7 | 荷物受渡書・出荷明細書発行API | https://smart-api-shipping.sagawa-exp.co.jp/api/ukewatashimeisai/xml |

### JSON形式でご利用の場合

| No. | API名称 | リクエストURL |
|-----|---------|----------------|
| 1 | 送り状発行API | https://smart-api-shipping.sagawa-exp.co.jp/api/shipping/json |
| 2 | 即時発行API | https://smart-api-shipping.sagawa-exp.co.jp/api/sokuji/json |
| 3 | ファイル存在確認API | https://smart-api-shipping.sagawa-exp.co.jp/api/checkfile/json |
| 4 | 利用実績API | https://smart-api-shipping.sagawa-exp.co.jp/api/riyoujisseki/json |
| 5 | 送り状再発行依頼API | https://smart-api-shipping.sagawa-exp.co.jp/api/retryprint/json |
| 6 | 佐川急便マスタ参照API | https://smart-api-shipping.sagawa-exp.co.jp/api/checkaddress/json |
| 7 | 荷物受渡書・出荷明細書発行API | https://smart-api-shipping.sagawa-exp.co.jp/api/ukewatashimeisai/json |

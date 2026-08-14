# Windows PC セットアップ手順

このシステムを新しいWindows PCで動かすための手順です。上から順番に実行してください。

---

## 1. 前提ソフトのインストール

以下をこの順番でインストールしてください。

1. **Python 3.11以降**: https://www.python.org/downloads/windows/
   インストール時に「Add python.exe to PATH」に必ずチェックを入れてください。
2. **Git**: https://git-scm.com/download/win
3. **cloudflared**（スマホからアクセスするためのトンネル）:
   `winget`でインストールすると、PowerShellのPATHに反映されるタイミングが不安定で
   （ウィンドウを開き直しても反映されない・タスクスケジューラからは見えない等）
   「指定されたファイルが見つかりません」エラーが繰り返し発生したため、
   **PATHに頼らずプロジェクト内に直接配置する方式**を採用しています（SumatraPDFと同じ考え方）。

   https://github.com/cloudflare/cloudflared/releases から最新版の `cloudflared-windows-amd64.exe` をダウンロードし、
   `cloudflared.exe` にリネームしてこのプロジェクトの `tools\cloudflared.exe` として配置してください
   （`tools`フォルダが無ければ作成。手順4のSumatraPDFと同じフォルダです）。
   `windows\start_app.ps1` は起動のたびに `tools\cloudflared.exe` を最優先で探すため、
   一度配置すればPATHの状態やPowerShellウィンドウの開き直しに影響されず、常に同じ場所から確実に起動します。
4. **SumatraPDF**（推奨・印刷を安定させるため）: https://www.sumatrapdfreader.org/download-free-pdf-viewer
   ポータブル版をダウンロードし、`SumatraPDF.exe` をこのプロジェクトの `tools\SumatraPDF.exe` として配置してください（`tools`フォルダが無ければ作成）。
   - 導入しない場合、既定のPDFビューア経由での印刷にフォールバックしますが、動作が不安定な場合があります。

---

## 2. リポジトリの取得

```powershell
cd C:\
git clone git@github.com:toratyann620/ph-label-print.git
cd ph-label-print
```

SSH接続でエラーになる場合は、このPCでGitHubのSSHキーを設定してください（`ssh-keygen` → GitHubの Settings > SSH and GPG keys に公開鍵を登録）。

---

## 3. Python環境のセットアップ

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

---

## 4. 認証情報ファイル（.env / .env.test）の配置

**`.env` と `.env.test` はセキュリティ上GitHubに含まれていません。** 元のPC（Mac）から安全な方法（社内の共有ドライブ、パスワード付きZIP送付など）でこの2ファイルを受け取り、プロジェクトのルート（`ph-label-print\`直下、`requirements.txt`と同じ階層）に配置してください。

配置後、`data\` フォルダに`app.db`が自動作成されます（初回起動時）。

---

## 4.5. 初回PINの発行（重要）

管理画面（`/admin`）・スマホスキャン画面（`/scan`）はどちらもPIN認証で保護されています。初回のみ、以下のコマンドでPINを発行してください（発行後は`/admin/settings`から変更できます）。

```powershell
.venv\Scripts\python.exe scripts\init_pins.py
```

表示された「管理画面PIN」「スマホスキャンPIN」を控えておいてください。

---

## 5. プリンター設定の確認

Windowsの「設定 > Bluetoothとデバイス > プリンターとスキャナー」で、実際に使うプリンターの**正確な名前**を確認してください。

起動後、管理画面（後述）の「設定」画面で、各ブランドの「プリンター名」欄にこの名前を入力してください。

---

## 6. 動作確認（手動起動）

```powershell
$env:APP_ENV_FILE = ".env"
.venv\Scripts\python.exe -m uvicorn src.common.app:app --host 0.0.0.0 --port 3131
```

ブラウザで `http://localhost:3131/admin/processing` が開けば成功です。`Ctrl+C`で停止してください。

---

## 7. 自動起動・自動終了の設定（毎日8:00起動 / 20:00終了）

PowerShellを**管理者として実行**し、以下を1回だけ実行してください。

```powershell
cd C:\ph-label-print
powershell -ExecutionPolicy Bypass -File windows\register_tasks.ps1
```

これで、タスクスケジューラに以下の2つのタスクが登録されます。

- `PHLabelPrint-Start`: 毎日8:00に自動でサーバーとCloudflare Tunnelを起動
- `PHLabelPrint-Stop`: 毎日20:00に自動で停止

タスクスケジューラアプリを開いて、登録されていることを確認してください。手動で今すぐ試したい場合は、該当タスクを右クリック→「実行」してください。

起動・停止スクリプトは `windows\start_app.ps1` / `windows\stop_app.ps1` です。ログは `windows\run\server.log` などに出力されます。

---

## 8. スマホ用URLの確認

起動後、`windows\run\tunnel.err.log` を開くと、以下のような行があります。

```
https://xxxxx-xxxxx-xxxxx-xxxxx.trycloudflare.com
```

このURLの末尾に `/scan` を付けたもの（例: `https://xxxxx.trycloudflare.com/scan`）をスタッフのスマホに共有してください。

**⚠️ 重要**: 現在は無料のクイックトンネルを使っているため、**サーバーを再起動するたびにURLが変わります**。毎日20:00に停止・8:00に再起動する運用のため、**このURLは毎日変わります**。

固定URL（例: `yamato.photopri.com`）が必要な場合は、`photopri.com`ドメインをCloudflareに登録すれば恒久的なURLに切り替えられます。ご希望があればお知らせください。

---

## 9. 運用開始後の更新方法

コードを更新する場合（Mac側で開発 → GitHubにpush → Windows側で反映）:

```powershell
cd C:\ph-label-print
powershell -ExecutionPolicy Bypass -File windows\stop_app.ps1
git pull
.venv\Scripts\pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File windows\start_app.ps1
```

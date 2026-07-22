<#
  本番サーバー（FastAPI）とCloudflare Tunnelを起動する。
  タスクスケジューラから 毎日8:00 に実行される想定。

  前提:
    - プロジェクトルートに .venv フォルダが作成済み（setup手順のREADME参照）
    - cloudflared.exe がPATHに通っている、または環境変数 CLOUDFLARED_PATH で指定
#>
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$runDir = Join-Path $root "windows\run"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

# 既に起動中なら二重起動しない
$serverPidFile = Join-Path $runDir "server.pid"
if (Test-Path $serverPidFile) {
    $existingPid = Get-Content $serverPidFile
    if (Get-Process -Id $existingPid -ErrorAction SilentlyContinue) {
        Write-Output "既にサーバーが起動しています (PID=$existingPid)。処理を終了します。"
        exit 0
    }
}

$env:APP_ENV_FILE = ".env"

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Error "venvが見つかりません: $venvPython 。先にREADMEのセットアップ手順を実行してください。"
    exit 1
}

# ── FastAPIサーバー起動（本番環境）──────────────────────────
$server = Start-Process -FilePath $venvPython `
    -ArgumentList "-m", "uvicorn", "src.common.app:app", "--host", "0.0.0.0", "--port", "3131" `
    -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $runDir "server.log") `
    -RedirectStandardError  (Join-Path $runDir "server.err.log")
$server.Id | Out-File (Join-Path $runDir "server.pid")
Write-Output "サーバーを起動しました (PID=$($server.Id))"

Start-Sleep -Seconds 3

# ── Cloudflare Tunnel起動 ────────────────────────────────
$cloudflaredPath = $env:CLOUDFLARED_PATH
if (-not $cloudflaredPath) { $cloudflaredPath = "cloudflared.exe" }

try {
    $tunnel = Start-Process -FilePath $cloudflaredPath `
        -ArgumentList "tunnel", "--url", "http://localhost:3131" `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runDir "tunnel.log") `
        -RedirectStandardError  (Join-Path $runDir "tunnel.err.log")
    $tunnel.Id | Out-File (Join-Path $runDir "tunnel.pid")
    Write-Output "Cloudflare Tunnelを起動しました (PID=$($tunnel.Id))"
    Write-Output "数秒後に windows\run\tunnel.err.log 内のURL（https://xxxx.trycloudflare.com）を確認してください。"
} catch {
    Write-Warning "Cloudflare Tunnelの起動に失敗しました: $_"
    Write-Warning "cloudflared.exe がインストールされているか確認してください。"
}

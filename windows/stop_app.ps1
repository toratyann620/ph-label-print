<#
  本番サーバーとCloudflare Tunnelを停止する。
  タスクスケジューラから 毎日20:00 に実行される想定。
#>
$root = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $root "windows\run"

foreach ($name in @("server", "tunnel")) {
    $pidFile = Join-Path $runDir "$name.pid"
    if (Test-Path $pidFile) {
        $procId = Get-Content $pidFile
        if (Get-Process -Id $procId -ErrorAction SilentlyContinue) {
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            Write-Output "$name を停止しました (PID=$procId)"
        }
        Remove-Item $pidFile -ErrorAction SilentlyContinue
    }
}

# 念のため、ポート3131を使っているプロセス・cloudflaredプロセスも掃除する
Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# ── 発行履歴・エラー履歴（DB）のバックアップ ──────────────────
# 万一のディスク障害・誤操作に備え、停止のたびに日付付きでコピーを残す（直近30世代を保持）
$dbFile = Join-Path $root "data\app.db"
if (Test-Path $dbFile) {
    $backupDir = Join-Path $root "data\backups"
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    Copy-Item $dbFile (Join-Path $backupDir "app_$stamp.db")

    Get-ChildItem $backupDir -Filter "app_*.db" | Sort-Object LastWriteTime -Descending |
        Select-Object -Skip 30 | Remove-Item -Force -ErrorAction SilentlyContinue

    Write-Output "DBをバックアップしました: data\backups\app_$stamp.db"
}

Write-Output "停止処理が完了しました。"

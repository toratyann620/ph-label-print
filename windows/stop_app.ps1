<#
  Stops the production server and Cloudflare Tunnel.
  Intended to be run daily at 20:00 by Task Scheduler.

  NOTE: This file must stay plain ASCII (no Japanese text). Windows PowerShell 5.1
  does not reliably read UTF-8 .ps1 files without a BOM and will corrupt/garble
  non-ASCII characters, causing parse errors.
#>
$root = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $root "windows\run"

foreach ($name in @("server", "tunnel")) {
    $pidFile = Join-Path $runDir "$name.pid"
    if (Test-Path $pidFile) {
        $procId = Get-Content $pidFile
        if (Get-Process -Id $procId -ErrorAction SilentlyContinue) {
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            Write-Output "Stopped $name (PID=$procId)"
        }
        Remove-Item $pidFile -ErrorAction SilentlyContinue
    }
}

# Also clean up any stray cloudflared process just in case
Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# ── Backup the shipment/error history DB ────────────────────────
# Keep a dated copy on every stop in case of disk failure or accidental data loss
# (keeps the most recent 30 backups).
$dbFile = Join-Path $root "data\app.db"
if (Test-Path $dbFile) {
    $backupDir = Join-Path $root "data\backups"
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    Copy-Item $dbFile (Join-Path $backupDir "app_$stamp.db")

    Get-ChildItem $backupDir -Filter "app_*.db" | Sort-Object LastWriteTime -Descending |
        Select-Object -Skip 30 | Remove-Item -Force -ErrorAction SilentlyContinue

    Write-Output "Backed up DB to: data\backups\app_$stamp.db"
}

Write-Output "Stop completed."

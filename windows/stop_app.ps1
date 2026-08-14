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
            # /T kills the whole process tree. The venv's python.exe on Windows is a
            # launcher stub that spawns the real interpreter as a CHILD process rather
            # than running in-place; Stop-Process on just the stub's PID leaves that
            # child alive and still holding port 3131, causing the next start attempt
            # to fail with "address already in use" even though stop looked successful.
            try { & taskkill /F /T /PID $procId 2>$null | Out-Null } catch { }
            Write-Output "Stopped $name (PID=$procId)"
        }
        Remove-Item $pidFile -ErrorAction SilentlyContinue
    }
}

# Also clean up any stray cloudflared process just in case
Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# Also clean up any orphaned python process still holding port 3131
# (leftover from a start attempt before this taskkill /T fix was in place)
$staleServer = Get-NetTCPConnection -LocalPort 3131 -State Listen -ErrorAction SilentlyContinue
foreach ($conn in $staleServer) {
    try { & taskkill /F /T /PID $conn.OwningProcess 2>$null | Out-Null } catch { }
    Write-Output "Stopped orphaned process still holding port 3131 (PID=$($conn.OwningProcess))"
}
$stillHeld = Get-NetTCPConnection -LocalPort 3131 -State Listen -ErrorAction SilentlyContinue
if ($stillHeld) {
    Write-Warning "Port 3131 is still held by PID=$($stillHeld[0].OwningProcess) after stop. This is usually a permissions issue (that process was started elevated / by Task Scheduler). Re-run this script from an elevated (Run as Administrator) PowerShell window."
}

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

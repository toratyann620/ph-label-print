<#
  Starts the production server (FastAPI) and Cloudflare Tunnel.
  Intended to be run daily at 8:00 by Task Scheduler.

  Prerequisites:
    - .venv already created at the project root (see README setup steps)
    - cloudflared.exe on PATH, or set via the CLOUDFLARED_PATH env var

  NOTE: This file must stay plain ASCII (no Japanese text). Windows PowerShell 5.1
  does not reliably read UTF-8 .ps1 files without a BOM and will corrupt/garble
  non-ASCII characters, causing parse errors.
#>
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$runDir = Join-Path $root "windows\run"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

# Skip if already running
$serverPidFile = Join-Path $runDir "server.pid"
if (Test-Path $serverPidFile) {
    $existingPid = Get-Content $serverPidFile
    if (Get-Process -Id $existingPid -ErrorAction SilentlyContinue) {
        Write-Output "Server is already running (PID=$existingPid). Exiting."
        exit 0
    }
}

# Free port 3131 if a stale/orphaned process is still holding it.
# (stop_app.ps1 kills the PID it recorded, but if that PID was already wrong
# or a previous start crashed without updating server.pid, an old process can
# keep the port occupied. When that happens, this script used to launch a new
# server that silently failed to bind while the stale process kept answering
# requests with outdated code, with no visible error to the operator.)
# Retries a few times: on Windows, the venv's python.exe is a launcher stub
# that runs the real interpreter as a CHILD process, so a single kill pass can
# still leave a grandchild holding the port; taskkill /T targets the whole tree.
for ($attempt = 1; $attempt -le 5; $attempt++) {
    $portHolders = Get-NetTCPConnection -LocalPort 3131 -State Listen -ErrorAction SilentlyContinue
    if (-not $portHolders) { break }
    foreach ($conn in $portHolders) {
        $staleId = $conn.OwningProcess
        Write-Warning "Port 3131 is already in use by PID=$staleId (stale process from a previous run). Stopping it (attempt $attempt)."
        # A failed taskkill (e.g. insufficient privileges) must not abort this script
        # (with $ErrorActionPreference=Stop, an unhandled native-command failure would).
        try { & taskkill /F /T /PID $staleId 2>$null | Out-Null } catch { }
    }
    Start-Sleep -Seconds 2
}

$stillBlocked = Get-NetTCPConnection -LocalPort 3131 -State Listen -ErrorAction SilentlyContinue
if ($stillBlocked) {
    $blockedPid = $stillBlocked[0].OwningProcess
    $msg = "Could not free port 3131 (still held by PID=$blockedPid). This is usually a permissions issue " +
           "(that process was started elevated / by Task Scheduler and this session is not elevated). " +
           "Re-run this script from an elevated (Run as Administrator) PowerShell window."
    Write-Error $msg
    exit 1
}

$env:APP_ENV_FILE = ".env"

# Force UTF-8 for Python's stdout/stderr regardless of the Windows console's
# legacy codepage (cp932 on Japanese Windows). Without this, print() calls
# containing certain symbols (e.g. warning/check marks) raise UnicodeEncodeError
# and crash the request instead of returning the intended error response.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Error "venv not found: $venvPython . Please run the README setup steps first."
    exit 1
}

# ── Start FastAPI server (production) ──────────────────────────
$server = Start-Process -FilePath $venvPython `
    -ArgumentList "-m", "uvicorn", "src.common.app:app", "--host", "0.0.0.0", "--port", "3131" `
    -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $runDir "server.log") `
    -RedirectStandardError  (Join-Path $runDir "server.err.log")
$server.Id | Out-File (Join-Path $runDir "server.pid")
Write-Output "Server started (PID=$($server.Id))"

Start-Sleep -Seconds 3

# Verify the server process is still alive (it exits immediately on a bind
# failure such as "port already in use"). Fail loudly here instead of leaving
# a silently-broken server running with no visible error.
if (-not (Get-Process -Id $server.Id -ErrorAction SilentlyContinue)) {
    Write-Error "Server process (PID=$($server.Id)) exited immediately after starting. Check windows\run\server.err.log for details."
    Remove-Item (Join-Path $runDir "server.pid") -ErrorAction SilentlyContinue
    exit 1
}

# ── Start Cloudflare Tunnel ─────────────────────────────────────
# Uses the free quick tunnel (URL changes every restart). A fixed entry URL
# is provided separately via a redirect hosted on muog.co.jp; see the
# "Update the fixed-URL redirect" section below.
#
# cloudflared.exe resolution order (avoids relying on the system PATH, which has
# repeatedly failed to be visible to Task Scheduler / freshly opened PowerShell
# sessions after a winget install):
#   1. CLOUDFLARED_PATH environment variable, if set
#   2. Bundled copy at tools\cloudflared.exe (same approach as SumatraPDF; see README)
#   3. "cloudflared.exe" via system PATH (last resort, kept for compatibility)
$cloudflaredPath = $env:CLOUDFLARED_PATH
if (-not $cloudflaredPath) {
    $bundled = Join-Path $root "tools\cloudflared.exe"
    if (Test-Path $bundled) {
        $cloudflaredPath = $bundled
    } else {
        $cloudflaredPath = "cloudflared.exe"
    }
}
Write-Output "Using cloudflared: $cloudflaredPath"

$tunnelArgs = @("tunnel", "--url", "http://localhost:3131")

$tunnelStarted = $false
try {
    $tunnel = Start-Process -FilePath $cloudflaredPath `
        -ArgumentList $tunnelArgs `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runDir "tunnel.log") `
        -RedirectStandardError  (Join-Path $runDir "tunnel.err.log")
    $tunnel.Id | Out-File (Join-Path $runDir "tunnel.pid")
    Write-Output "Cloudflare Tunnel started (PID=$($tunnel.Id))"
    $tunnelStarted = $true
} catch {
    Write-Warning "Failed to start Cloudflare Tunnel: $_"
    Write-Warning "Please confirm cloudflared.exe is installed."
}

# -- Resolve the public URL and print a ready-to-use summary -----
# (so the operator does not need to separately grep tunnel.err.log and query
# the database for PINs every time the app is restarted)
$tunnelUrl = $null
if ($tunnelStarted) {
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 1
        $logLines = Get-Content (Join-Path $runDir "tunnel.err.log") -ErrorAction SilentlyContinue
        $found = $logLines | Select-String -Pattern "https://[A-Za-z0-9\-]+\.trycloudflare\.com" | Select-Object -First 1
        if ($found) {
            $tunnelUrl = $found.Matches[0].Value
            break
        }
    }
}

# -- Update the fixed-URL redirect (muog.co.jp/label-print/) ----
# The quick-tunnel URL changes every restart, so staff instead use a fixed
# entry URL (e.g. https://muog.co.jp/label-print/scan) hosted separately on
# the muog.co.jp server, which 302-redirects to whatever URL is current.
# Push the new URL to that redirect endpoint here on every start. If
# REDIRECT_UPDATE_URL/REDIRECT_UPDATE_SECRET are not set in .env, this is
# skipped and the direct trycloudflare.com URL is used as before.
function Get-EnvValue($key) {
    $envFile = Join-Path $root ".env"
    if (-not (Test-Path $envFile)) { return $null }
    $line = Get-Content $envFile | Where-Object { $_ -match "^\s*$key\s*=" } | Select-Object -Last 1
    if (-not $line) { return $null }
    return ($line -replace "^\s*$key\s*=", "").Trim().Trim('"')
}

if ($tunnelUrl) {
    $redirectUpdateUrl = Get-EnvValue "REDIRECT_UPDATE_URL"
    $redirectUpdateSecret = Get-EnvValue "REDIRECT_UPDATE_SECRET"
    if ($redirectUpdateUrl -and $redirectUpdateSecret) {
        try {
            $resp = Invoke-WebRequest -Uri $redirectUpdateUrl -Method Get -Body @{ secret = $redirectUpdateSecret; url = $tunnelUrl } -UseBasicParsing -TimeoutSec 10
            Write-Output "Fixed-URL redirect updated: $($resp.Content)"
        } catch {
            Write-Warning "Failed to update fixed-URL redirect: $_"
        }
    }
}

$pins = $null
try {
    $pinsJson = & $venvPython -c "import sys; sys.path.insert(0, 'src/common'); import db, json; s = db.get_app_settings(); print(json.dumps({'admin_pin': s['admin_pin'], 'scan_pin': s['scan_pin']}))"
    $pins = $pinsJson | ConvertFrom-Json
} catch {
    Write-Warning "Failed to read PINs from the database: $_"
}

Write-Output ""
Write-Output "=================================================="
if ($tunnelUrl) {
    if ($redirectUpdateUrl -and $redirectUpdateSecret) {
        Write-Output "  Admin screen : https://muog.co.jp/label-print/admin/processing"
        Write-Output "  Scan screen  : https://muog.co.jp/label-print/scan"
        Write-Output "  (direct tunnel URL, for troubleshooting: $tunnelUrl)"
    } else {
        Write-Output "  Admin screen : $tunnelUrl/admin/processing"
        Write-Output "  Scan screen  : $tunnelUrl/scan"
    }
} else {
    Write-Output "  Tunnel URL not detected within 15s."
    Write-Output "  Check manually: windows\run\tunnel.err.log"
}
if ($pins) {
    Write-Output "  Admin PIN    : $($pins.admin_pin)"
    Write-Output "  Scan PIN     : $($pins.scan_pin)"
}
Write-Output "=================================================="

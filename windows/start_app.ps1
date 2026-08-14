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

$env:APP_ENV_FILE = ".env"

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

# ── Start Cloudflare Tunnel ─────────────────────────────────────
# If a fixed-URL setup exists (windows\tunnel-credentials.json), use the named
# tunnel; otherwise fall back to the quick tunnel (URL changes every restart).
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

$credentialsFile = Join-Path $root "windows\tunnel-credentials.json"
$configFile = Join-Path $root "windows\cloudflared_config.yml"

if (Test-Path $credentialsFile) {
    $tunnelArgs = @("tunnel", "--config", $configFile, "run", "ph-label-print")
    Write-Output "Starting Cloudflare Tunnel with fixed URL (label-print.muog.co.jp)."
} else {
    $tunnelArgs = @("tunnel", "--url", "http://localhost:3131")
    Write-Output "No fixed-URL setup found (windows\tunnel-credentials.json missing). Using a temporary quick-tunnel URL."
}

try {
    $tunnel = Start-Process -FilePath $cloudflaredPath `
        -ArgumentList $tunnelArgs `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runDir "tunnel.log") `
        -RedirectStandardError  (Join-Path $runDir "tunnel.err.log")
    $tunnel.Id | Out-File (Join-Path $runDir "tunnel.pid")
    Write-Output "Cloudflare Tunnel started (PID=$($tunnel.Id))"
    if (Test-Path $credentialsFile) {
        Write-Output "URL: https://label-print.muog.co.jp"
    } else {
        Write-Output "In a few seconds, check windows\run\tunnel.err.log for the URL (https://xxxx.trycloudflare.com)."
    }
} catch {
    Write-Warning "Failed to start Cloudflare Tunnel: $_"
    Write-Warning "Please confirm cloudflared.exe is installed."
}

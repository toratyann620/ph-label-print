<#
  Registers a Task Scheduler job that runs the daily Shopify fulfillment batch
  at 18:00 every day (marks issued orders as "fulfilled" in Shopify, which
  triggers Shopify's automatic shipping-confirmation email to the customer).

  This task is independent from the app start/stop tasks: it only reads the
  local database and calls the Shopify API, so it does not need the FastAPI
  server or cloudflared tunnel to be running, and does not affect the tunnel URL.

  Run this script once, from a normal (non-administrator) PowerShell window:

    powershell -ExecutionPolicy Bypass -File windows\register_fulfillment_task.ps1

  NOTE: This file must stay plain ASCII (no Japanese text). Windows PowerShell 5.1
  does not reliably read UTF-8 .ps1 files without a BOM and will corrupt/garble
  non-ASCII characters, causing parse errors.
#>
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$script = Join-Path $root "scripts\daily_fulfillment.py"
$logDir = Join-Path $root "windows\run"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "fulfillment.log"

# Wrapped in cmd.exe to redirect output to a log file (Task Scheduler runs with
# no visible console, so this is the only way to inspect what happened later).
$cmdArgument = "/c `"`"$venvPython`" `"$script`" >> `"$logFile`" 2>&1`""
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $cmdArgument -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At 6:00PM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "PHLabelPrint-DailyFulfillment" -Action $action -Trigger $trigger `
    -Settings $settings -Force | Out-Null

Write-Output "Registered: PHLabelPrint-DailyFulfillment (daily at 18:00)"
Write-Output "Log output will be appended to: $logFile"
Write-Output "To test immediately, right-click the task in Task Scheduler and choose Run, then check the log file."

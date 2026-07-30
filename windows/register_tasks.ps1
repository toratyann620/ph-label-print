<#
  Registers Task Scheduler jobs: start daily at 8:00, stop daily at 20:00.
  Run this script once, from a PowerShell window opened as Administrator:

    powershell -ExecutionPolicy Bypass -File windows\register_tasks.ps1

  NOTE: This file must stay plain ASCII (no Japanese text). Windows PowerShell 5.1
  does not reliably read UTF-8 .ps1 files without a BOM and will corrupt/garble
  non-ASCII characters, causing parse errors.
#>
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $root "windows\start_app.ps1"
$stopScript  = Join-Path $root "windows\stop_app.ps1"

$startAction  = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$startScript`""
$startTrigger = New-ScheduledTaskTrigger -Daily -At 8:00AM
$settings     = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "PHLabelPrint-Start" -Action $startAction -Trigger $startTrigger `
    -Settings $settings -RunLevel Highest -Force | Out-Null
Write-Output "Registered: PHLabelPrint-Start (daily at 8:00)"

$stopAction  = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$stopScript`""
$stopTrigger = New-ScheduledTaskTrigger -Daily -At 8:00PM
Register-ScheduledTask -TaskName "PHLabelPrint-Stop" -Action $stopAction -Trigger $stopTrigger `
    -Settings $settings -RunLevel Highest -Force | Out-Null
Write-Output "Registered: PHLabelPrint-Stop (daily at 20:00)"

Write-Output ""
Write-Output "Check: open Task Scheduler and confirm PHLabelPrint-Start / PHLabelPrint-Stop are listed."
Write-Output "To test immediately, right-click either task in Task Scheduler and choose Run."

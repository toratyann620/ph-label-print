<#
  タスクスケジューラに「毎日8:00起動 / 毎日20:00終了」を登録する。
  PowerShellを「管理者として実行」した状態で、このスクリプトを1回だけ実行してください。

    powershell -ExecutionPolicy Bypass -File windows\register_tasks.ps1
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
Write-Output "登録: PHLabelPrint-Start（毎日 8:00 起動）"

$stopAction  = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$stopScript`""
$stopTrigger = New-ScheduledTaskTrigger -Daily -At 8:00PM
Register-ScheduledTask -TaskName "PHLabelPrint-Stop" -Action $stopAction -Trigger $stopTrigger `
    -Settings $settings -RunLevel Highest -Force | Out-Null
Write-Output "登録: PHLabelPrint-Stop（毎日 20:00 終了）"

Write-Output ""
Write-Output "確認: タスクスケジューラを開いて「PHLabelPrint-Start」「PHLabelPrint-Stop」が登録されていることを確認してください。"
Write-Output "今すぐ動作確認したい場合は、タスクスケジューラで右クリック→「実行」で手動起動できます。"

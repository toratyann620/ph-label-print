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

Write-Output "停止処理が完了しました。"

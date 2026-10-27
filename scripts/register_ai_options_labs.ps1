$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $root "scripts\run_ai_options_lab.ps1"

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvCommand) {
    throw "uv not found. Run scripts/bootstrap.ps1 first."
}

function Register-LaneTask {
    param(
        [string]$TaskName,
        [string]$Lane,
        $Trigger,
        [string]$Description
    )
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -Lane `"$Lane`""
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -WakeToRun `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
        -RestartCount 2 `
        -RestartInterval (New-TimeSpan -Minutes 5)
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $Trigger `
        -Settings $settings `
        -Description $Description `
        -Force | Out-Null
    Write-Output "Registered scheduled task: $TaskName"
}

$now = Get-Date
$minute = if ($now.Minute -lt 30) { 16 } else { 46 }
$firstEth = $now.Date.AddHours($now.Hour).AddMinutes($minute)
if ($firstEth -le $now) {
    $firstEth = $firstEth.AddHours(1)
}
$ethTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At $firstEth `
    -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$btcTrigger = New-ScheduledTaskTrigger -Daily -At "07:45"

Register-LaneTask `
    -TaskName "TradingBotAIOptionsEth" `
    -Lane "eth" `
    -Trigger $ethTrigger `
    -Description "ETH-only AI options paper lane; long premium only; paper only"

Register-LaneTask `
    -TaskName "TradingBotAIOptionsBtcLab" `
    -Lane "btc-lab" `
    -Trigger $btcTrigger `
    -Description "BTC-only $100k paper contract-plumbing lab; long premium only; paper only"

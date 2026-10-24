$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $root "scripts\run_ai_options_30m.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""

$now = Get-Date
$minute = if ($now.Minute -lt 30) { 31 } else { 1 }
$firstRun = $now.Date.AddHours($now.Hour).AddMinutes($minute)
if ($firstRun -le $now) {
    $firstRun = $firstRun.AddHours(1)
}

$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At $firstRun `
    -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5)

try {
    Register-ScheduledTask `
        -TaskName "TradingBotAIOptions30m" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "30-minute AI crypto-options paper cycle (long premium only; paper only)" `
        -Force | Out-Null
    Write-Output "Registered scheduled task: TradingBotAIOptions30m (every 30 minutes; paper only)"
} catch {
    Write-Output "Could not register the scheduled task automatically."
    Write-Output "Run this script from an elevated PowerShell, or create the task manually."
    Write-Output $_.Exception.Message
}

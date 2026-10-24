$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $root "scripts\run_intraday_cycle.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""

# Run one cycle at :01 every hour, starting at the next hour. The cycle only
# uses completed 1h bars; it never trades the still-forming bar.
$now = Get-Date
$firstRun = $now.Date.AddHours($now.Hour + 1).AddMinutes(1)
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At $firstRun `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
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
        -TaskName "TradingBotIntraday" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Hourly deterministic intraday paper cycle (completed 1h bars; paper only)" `
        -Force | Out-Null
    Write-Output "Registered scheduled task: TradingBotIntraday (hourly, paper only)"
} catch {
    Write-Output "Could not register the scheduled task automatically."
    Write-Output "Run this script from an elevated PowerShell, or create the task manually."
    Write-Output $_.Exception.Message
}

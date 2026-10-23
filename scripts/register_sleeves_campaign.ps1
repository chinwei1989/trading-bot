$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $root "scripts\run_sleeves.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""

$trigger = New-ScheduledTaskTrigger -Daily -At "07:20"

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

try {
    Register-ScheduledTask `
        -TaskName "TradingBotSleeves" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Separate paper sleeves: breakout, reversal, meta allocator" `
        -Force | Out-Null
    Write-Output "Registered scheduled task: TradingBotSleeves (daily 07:20 local)"
} catch {
    Write-Output "Could not register the scheduled task automatically."
    Write-Output "Run this script from an elevated PowerShell, or create the task manually."
    Write-Output $_.Exception.Message
}

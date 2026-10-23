$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $root "scripts\run_campaign.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""

$trigger = New-ScheduledTaskTrigger -Daily -At "07:00"

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

try {
    Register-ScheduledTask `
        -TaskName "TradingBotPaperCampaign" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Daily paper campaign: trend + XSMOM + evaluation" `
        -Force | Out-Null
    Write-Output "Registered scheduled task: TradingBotPaperCampaign (daily 07:00 local)"
} catch {
    Write-Output "Could not register the scheduled task automatically."
    Write-Output "Run this script from an elevated PowerShell, or create the task manually."
    Write-Output $_.Exception.Message
}

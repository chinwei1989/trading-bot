$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $root "scripts\run_ai_squad.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""

# Run after the deterministic campaign (07:00), single-provider AI (07:15),
# and sleeve campaign (07:20), but before the 07:30 health check.
$trigger = New-ScheduledTaskTrigger -Daily -At "07:25"

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

try {
    Register-ScheduledTask `
        -TaskName "TradingBotAISquad" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Separate seven-agent AI squad paper pipeline (paper only)" `
        -Force | Out-Null
    Write-Output "Registered scheduled task: TradingBotAISquad (daily 07:25 local)"
} catch {
    Write-Output "Could not register the scheduled task automatically."
    Write-Output "Run this script from an elevated PowerShell, or create the task manually."
    Write-Output $_.Exception.Message
}

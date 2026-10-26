$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $root "scripts\run_options_swing.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""

$trigger = New-ScheduledTaskTrigger -Daily -At "07:40"

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5)

try {
    Register-ScheduledTask `
        -TaskName "TradingBotOptionsSwing" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Daily deterministic BTC/ETH swing-options paper cycle (long premium only; paper only)" `
        -Force | Out-Null
    Write-Output "Registered scheduled task: TradingBotOptionsSwing (daily 07:40 local)"
} catch {
    Write-Output "Could not register the scheduled task automatically."
    Write-Output "Run this script from an elevated PowerShell, or create the task manually."
    Write-Output $_.Exception.Message
    exit 1
}

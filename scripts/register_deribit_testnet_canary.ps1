$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $root "scripts\run_deribit_testnet_canary.ps1"

$id = [Environment]::GetEnvironmentVariable("DERIBIT_CLIENT_ID", "User")
$secret = [Environment]::GetEnvironmentVariable("DERIBIT_CLIENT_SECRET", "User")
if (-not $id -or -not $secret) {
    throw "Set DERIBIT_CLIENT_ID and DERIBIT_CLIENT_SECRET in the Windows user environment before registering the canary task."
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""

$trigger = New-ScheduledTaskTrigger -Daily -At "06:45"

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5)

try {
    Register-ScheduledTask `
        -TaskName "TradingBotDeribitCanary" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Daily Deribit testnet execution canary (testnet only; no live orders)" `
        -Force | Out-Null
    Write-Output "Registered scheduled task: TradingBotDeribitCanary (daily 06:45 local)"
} catch {
    Write-Output "Could not register the scheduled task automatically."
    Write-Output "Run this script from an elevated PowerShell, or create the task manually."
    Write-Output $_.Exception.Message
    exit 1
}

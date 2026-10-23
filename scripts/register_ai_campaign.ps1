$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $root "scripts\run_ai_pipeline.ps1"
$configText = Get-Content (Join-Path $root "config\ai_agent.yaml") -Raw
$envFile = Join-Path $root ".env"
$hasEnvKey = [bool]$env:TYPESAFE_API_KEY
$hasFileKey = (Test-Path $envFile) -and [bool](Select-String -Path $envFile -Pattern "^TYPESAFE_API_KEY=.+")
if (($configText -match "provider:\s*jev") -and (-not ($hasEnvKey -or $hasFileKey))) {
    throw "Set TYPESAFE_API_KEY (environment or .env) before registering the Jev paper task. No task was created."
}

# Separate account and task. The AI pipeline fails closed if its provider is
# not configured, so register this only after setting TYPESAFE_API_KEY or a
# local OpenAI-compatible endpoint in config/ai_agent.yaml.
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""

$trigger = New-ScheduledTaskTrigger -Daily -At "07:15"

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

try {
    Register-ScheduledTask `
        -TaskName "TradingBotAIPaper" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Separate AI-agent paper pipeline (paper only; fails closed without provider)" `
        -Force | Out-Null
    Write-Output "Registered scheduled task: TradingBotAIPaper (daily 07:15 local)"
} catch {
    Write-Output "Could not register the scheduled task automatically."
    Write-Output "Run this script from an elevated PowerShell, or create the task manually."
    Write-Output $_.Exception.Message
}

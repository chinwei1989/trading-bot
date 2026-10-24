# Check whether this Windows PC is suitable as an always-on paper host.

param(
    [string]$OutDir = "artifacts"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

function Get-PowerIndex {
    param([string]$Subgroup, [string]$Setting)
    $text = powercfg /query SCHEME_CURRENT $Subgroup $Setting 2>$null
    $line = $text | Select-String "Current AC Power Setting Index" | Select-Object -First 1
    if (-not $line) { return $null }
    $raw = ($line.ToString() -split ":")[-1].Trim()
    try { return [Convert]::ToInt32($raw, 16) } catch { return $null }
}

$standbyAc = Get-PowerIndex "SUB_SLEEP" "STANDBYIDLE"
$hibernateAc = Get-PowerIndex "SUB_SLEEP" "HIBERNATEIDLE"
$battery = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue
$time = Get-Service w32time -ErrorAction SilentlyContinue
$taskRows = @()
foreach ($task in Get-ScheduledTask -TaskName "TradingBot*" -ErrorAction SilentlyContinue) {
    $info = Get-ScheduledTaskInfo -TaskName $task.TaskName
    $taskRows += [pscustomobject]@{
        name = $task.TaskName
        state = [string]$task.State
        last_run = if ($info.LastRunTime) { $info.LastRunTime.ToString("o") } else { $null }
        last_result = $info.LastTaskResult
        next_run = if ($info.NextRunTime) { $info.NextRunTime.ToString("o") } else { $null }
        wake_to_run = [bool]$task.Settings.WakeToRun
        start_when_available = [bool]$task.Settings.StartWhenAvailable
        logon_type = [string]$task.Principal.LogonType
    }
}
$networkBinance = Test-NetConnection data-api.binance.vision -Port 443 -InformationLevel Quiet
$networkDeribit = Test-NetConnection www.deribit.com -Port 443 -InformationLevel Quiet
$disk = Get-PSDrive C
$boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
$timeStatus = if ($time) { [string]$time.Status } else { "missing" }
$badTasks = @($taskRows | Where-Object { $_.last_result -ne 0 -or -not $_.wake_to_run })
$interactive = @($taskRows | Where-Object { $_.logon_type -eq "Interactive" })

$recommendations = @()
if ($timeStatus -ne "Running") {
    $recommendations += "Run an elevated PowerShell: Set-Service w32time -StartupType Automatic; Start-Service w32time; w32tm /resync"
}
if ($standbyAc -ne 0) {
    $recommendations += "Disable AC sleep: powercfg /change standby-timeout-ac 0"
}
if ($interactive.Count -gt 0) {
    $recommendations += "Tasks use Interactive logon; keep the Windows user signed in, or install a service/credentialed task principal for unattended reboots."
}
if (-not $networkBinance -or -not $networkDeribit) {
    $recommendations += "Check outbound HTTPS to Binance and Deribit."
}
if (($disk.Free / 1GB) -lt 10) {
    $recommendations += "Free disk space; less than 10 GB remains."
}

$networkOk = $networkBinance -and $networkDeribit
$status = if (
    $timeStatus -eq "Running" -and
    $standbyAc -eq 0 -and
    $networkOk -and
    $badTasks.Count -eq 0 -and
    $interactive.Count -eq 0
) { "READY" } else { "DEGRADED" }

$report = [pscustomobject]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    status = $status
    host = $env:COMPUTERNAME
    user = $env:USERNAME
    uptime_hours = [math]::Round(((Get-Date) - $boot).TotalHours, 1)
    free_disk_gb = [math]::Round($disk.Free / 1GB, 1)
    battery_present = [bool]$battery
    ac_sleep_seconds = $standbyAc
    ac_hibernate_seconds = $hibernateAc
    time_service = $timeStatus
    network_binance = [bool]$networkBinance
    network_deribit = [bool]$networkDeribit
    tasks = $taskRows
    recommendations = $recommendations
}

$jsonPath = Join-Path $OutDir "HOST_READINESS.json"
$mdPath = Join-Path $OutDir "HOST_READINESS.md"
$jsonText = $report | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText(
    (Resolve-Path $OutDir).Path + "\HOST_READINESS.json",
    $jsonText,
    (New-Object System.Text.UTF8Encoding($false))
)
$lines = @(
    "# Host readiness",
    "",
    "**Status: $status**",
    "",
    "- Host: ``$($report.host)``",
    "- User: ``$($report.user)``",
    "- Uptime: **$($report.uptime_hours) h**",
    "- Free C: **$($report.free_disk_gb) GB**",
    "- AC sleep: **$standbyAc s**",
    "- AC hibernate: **$hibernateAc s**",
    "- Windows Time: **$timeStatus**",
    "- Binance HTTPS: **$networkBinance**",
    "- Deribit HTTPS: **$networkDeribit**",
    "",
    "| Task | State | Last result | Wake | Logon | Next run |",
    "|---|---|---:|---|---|---|"
)
foreach ($task in $taskRows) {
    $lines += "| $($task.name) | $($task.state) | $($task.last_result) | $($task.wake_to_run) | $($task.logon_type) | $($task.next_run) |"
}
$lines += @("", "## Recommendations", "")
$lines += @($recommendations | ForEach-Object { "- $_" })
$lines += @("", "This report does not enable live trading.", "")
[System.IO.File]::WriteAllText(
    (Resolve-Path $OutDir).Path + "\HOST_READINESS.md",
    ($lines -join "`n"),
    (New-Object System.Text.UTF8Encoding($false))
)

Write-Output "host readiness: $status"
Write-Output "saved: $jsonPath"
Write-Output "saved: $mdPath"
if ($recommendations.Count -gt 0) {
    $recommendations | ForEach-Object { Write-Output "  - $_" }
}

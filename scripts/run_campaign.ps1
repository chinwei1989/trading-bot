param(
    [switch]$Reset
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force -Path "logs" | Out-Null

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCommand) {
    $uv = $uvCommand.Source
} elseif (Test-Path "$env:USERPROFILE\.local\bin\uv.exe") {
    $uv = "$env:USERPROFILE\.local\bin\uv.exe"
} else {
    throw "uv not found. Run scripts/bootstrap.ps1 first."
}

function Invoke-Step {
    param([string[]]$CliArgs, [string]$Label)
    "[$(Get-Date -Format o)] $Label" | Out-File -Append -Encoding utf8 "logs/campaign.log"
    & $uv @CliArgs 2>&1 | Out-File -Append -Encoding utf8 "logs/campaign.log"
    if ($LASTEXITCODE -ne 0) {
        "[$(Get-Date -Format o)] FAILED ($LASTEXITCODE): $Label" |
            Out-File -Append -Encoding utf8 "logs/campaign.log"
    }
}

$resetArg = @()
if ($Reset) { $resetArg = @("--reset") }

Invoke-Step @(
    "run", "python", "-m", "tradingbot",
    "--config", "config/base.yaml", "download"
) "download crypto data"

Invoke-Step (@(
    "run", "python", "-m", "tradingbot",
    "--config", "config/base.yaml",
    "run", "--mode", "paper", "--once", "--strategy", "trend"
) + $resetArg) "paper trend"

Invoke-Step (@(
    "run", "python", "-m", "tradingbot",
    "--config", "config/xsmom.yaml",
    "run", "--mode", "paper", "--once", "--strategy", "xsmom"
) + $resetArg) "paper xsmom"

Invoke-Step @(
    "run", "python", "scripts/daily_report.py",
    "--config", "config/base.yaml", "--strategy", "trend"
) "evaluate trend"

Invoke-Step @(
    "run", "python", "scripts/daily_report.py",
    "--config", "config/xsmom.yaml", "--strategy", "xsmom"
) "evaluate xsmom"

"[$(Get-Date -Format o)] campaign cycle complete" |
    Out-File -Append -Encoding utf8 "logs/campaign.log"

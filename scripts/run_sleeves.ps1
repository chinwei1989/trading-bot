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
    "[$(Get-Date -Format o)] $Label" | Out-File -Append -Encoding utf8 "logs/sleeves.log"
    & $uv @CliArgs 2>&1 | Out-File -Append -Encoding utf8 "logs/sleeves.log"
    if ($LASTEXITCODE -ne 0) {
        "[$(Get-Date -Format o)] FAILED ($LASTEXITCODE): $Label" |
            Out-File -Append -Encoding utf8 "logs/sleeves.log"
        exit $LASTEXITCODE
    }
}

$resetArg = @()
if ($Reset) { $resetArg = @("--reset") }

foreach ($name in @("breakout", "reversal", "meta")) {
    Invoke-Step (@(
        "run", "python", "-m", "tradingbot",
        "--config", "config/$name.yaml",
        "run", "--mode", "paper", "--once"
    ) + $resetArg) "paper $name"
    Invoke-Step @(
        "run", "python", "scripts/daily_report.py",
        "--config", "config/$name.yaml", "--strategy", $name
    ) "evaluate $name"
}

"[$(Get-Date -Format o)] sleeve campaign complete" |
    Out-File -Append -Encoding utf8 "logs/sleeves.log"

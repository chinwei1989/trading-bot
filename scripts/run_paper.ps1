param(
    [ValidateSet("trend", "xsmom")]
    [string]$Strategy = "trend",
    [string]$Config = "config/base.yaml",
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

$cliArgs = @(
    "run", "python", "-m", "tradingbot.cli",
    "--config", $Config,
    "run", "--mode", "paper", "--once", "--strategy", $Strategy
)
if ($Reset) { $cliArgs += "--reset" }

"[$(Get-Date -Format o)] paper run: $Strategy config=$Config reset=$Reset" |
    Out-File -Append -Encoding utf8 "logs/paper.log"
& $uv @cliArgs 2>&1 | Out-File -Append -Encoding utf8 "logs/paper.log"
exit $LASTEXITCODE

param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
New-Item -ItemType Directory -Force -Path "artifacts/intraday" | Out-Null

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCommand) {
    $uv = $uvCommand.Source
} elseif (Test-Path "$env:USERPROFILE\.local\bin\uv.exe") {
    $uv = "$env:USERPROFILE\.local\bin\uv.exe"
} else {
    throw "uv not found. Run scripts/bootstrap.ps1 first."
}

$mode = if ($DryRun) { "preview" } else { "paper" }
$cliArgs = @(
    "run", "python", "-m", "tradingbot",
    "--config", "config/intraday_meta.yaml",
    "run", "--mode", $mode, "--once", "--no-evaluate"
)

"[$(Get-Date -Format o)] intraday cycle start (mode=$mode)" |
    Out-File -Append -Encoding utf8 "logs/intraday.log"
# PowerShell 5.1 turns native stderr into ErrorRecords; do not let a harmless
# warning abort the cycle. The Python process exit code remains authoritative.
$previousErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $uv @cliArgs 2>&1 | Out-File -Append -Encoding utf8 "logs/intraday.log"
$code = $LASTEXITCODE
$ErrorActionPreference = $previousErrorAction
if ($code -ne 0) {
    "[$(Get-Date -Format o)] intraday cycle FAILED ($code)" |
        Out-File -Append -Encoding utf8 "logs/intraday.log"
    exit $code
}
"[$(Get-Date -Format o)] intraday cycle complete" |
    Out-File -Append -Encoding utf8 "logs/intraday.log"

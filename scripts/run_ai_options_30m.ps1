param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
New-Item -ItemType Directory -Force -Path "artifacts/ai_options_30m" | Out-Null

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCommand) {
    $uv = $uvCommand.Source
} elseif (Test-Path "$env:USERPROFILE\.local\bin\uv.exe") {
    $uv = "$env:USERPROFILE\.local\bin\uv.exe"
} else {
    throw "uv not found. Run scripts/bootstrap.ps1 first."
}

$cliArgs = @(
    "run", "python", "-m", "tradingbot",
    "--config", "config/ai_options_30m.yaml",
    "ai-options-run"
)
if ($DryRun) { $cliArgs += "--dry-run" }

"[$(Get-Date -Format o)] AI options cycle start (dry_run=$DryRun)" |
    Out-File -Append -Encoding utf8 "logs/ai_options_30m.log"
$previousErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $uv @cliArgs 2>&1 | Out-File -Append -Encoding utf8 "logs/ai_options_30m.log"
$code = $LASTEXITCODE
$ErrorActionPreference = $previousErrorAction
if ($code -ne 0) {
    "[$(Get-Date -Format o)] AI options cycle FAILED ($code)" |
        Out-File -Append -Encoding utf8 "logs/ai_options_30m.log"
    exit $code
}
"[$(Get-Date -Format o)] AI options cycle complete" |
    Out-File -Append -Encoding utf8 "logs/ai_options_30m.log"

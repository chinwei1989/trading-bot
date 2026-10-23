param(
    [switch]$Reset,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
New-Item -ItemType Directory -Force -Path "artifacts/ai_squad" | Out-Null

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCommand) {
    $uv = $uvCommand.Source
} elseif (Test-Path "$env:USERPROFILE\.local\bin\uv.exe") {
    $uv = "$env:USERPROFILE\.local\bin\uv.exe"
} else {
    throw "uv not found. Run scripts/bootstrap.ps1 first."
}

$cliArgs = @("run", "python", "-m", "tradingbot", "--config", "config/ai_squad.yaml", "ai-run")
if ($Reset) { $cliArgs += "--reset" }
if ($DryRun) { $cliArgs += "--dry-run" }

"[$(Get-Date -Format o)] AI squad start (reset=$Reset dry_run=$DryRun)" |
    Out-File -Append -Encoding utf8 "logs/ai_squad.log"
& $uv @cliArgs 2>&1 | Out-File -Append -Encoding utf8 "logs/ai_squad.log"
$code = $LASTEXITCODE
if ($code -ne 0) {
    "[$(Get-Date -Format o)] AI squad FAILED ($code)" |
        Out-File -Append -Encoding utf8 "logs/ai_squad.log"
    exit $code
}

"[$(Get-Date -Format o)] AI squad scorecard" |
    Out-File -Append -Encoding utf8 "logs/ai_squad.log"
& $uv run python -m tradingbot --config config/ai_squad.yaml ai-evaluate 2>&1 |
    Out-File -Append -Encoding utf8 "logs/ai_squad.log"
if ($LASTEXITCODE -ne 0) {
    "[$(Get-Date -Format o)] AI squad scorecard FAILED ($LASTEXITCODE)" |
        Out-File -Append -Encoding utf8 "logs/ai_squad.log"
    exit $LASTEXITCODE
}
"[$(Get-Date -Format o)] AI squad complete" |
    Out-File -Append -Encoding utf8 "logs/ai_squad.log"

param(
    [switch]$Reset,
    [switch]$DryRun,
    [string]$Provider = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
New-Item -ItemType Directory -Force -Path "artifacts/ai" | Out-Null

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCommand) {
    $uv = $uvCommand.Source
} elseif (Test-Path "$env:USERPROFILE\.local\bin\uv.exe") {
    $uv = "$env:USERPROFILE\.local\bin\uv.exe"
} else {
    throw "uv not found. Run scripts/bootstrap.ps1 first."
}

$cliArgs = @("run", "python", "-m", "tradingbot", "--config", "config/ai_agent.yaml", "ai-run")
if ($Reset) { $cliArgs += "--reset" }
if ($DryRun) { $cliArgs += "--dry-run" }
if ($Provider -ne "") { $cliArgs += @("--provider", $Provider) }

"[$(Get-Date -Format o)] AI pipeline start (provider=$Provider reset=$Reset dry_run=$DryRun)" |
    Out-File -Append -Encoding utf8 "logs/ai_pipeline.log"
& $uv @cliArgs 2>&1 | Out-File -Append -Encoding utf8 "logs/ai_pipeline.log"
$code = $LASTEXITCODE
if ($code -ne 0) {
    "[$(Get-Date -Format o)] AI pipeline FAILED ($code)" |
        Out-File -Append -Encoding utf8 "logs/ai_pipeline.log"
    exit $code
}

"[$(Get-Date -Format o)] AI scorecard" |
    Out-File -Append -Encoding utf8 "logs/ai_pipeline.log"
& $uv run python -m tradingbot --config config/ai_agent.yaml ai-evaluate 2>&1 |
    Out-File -Append -Encoding utf8 "logs/ai_pipeline.log"
if ($LASTEXITCODE -ne 0) {
    "[$(Get-Date -Format o)] AI scorecard FAILED ($LASTEXITCODE)" |
        Out-File -Append -Encoding utf8 "logs/ai_pipeline.log"
    exit $LASTEXITCODE
}
"[$(Get-Date -Format o)] AI pipeline complete" |
    Out-File -Append -Encoding utf8 "logs/ai_pipeline.log"

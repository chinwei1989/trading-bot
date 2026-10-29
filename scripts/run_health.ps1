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

"[$(Get-Date -Format o)] campaign health check" |
    Out-File -Append -Encoding utf8 "logs/health.log"
& $uv run python -m tradingbot health --notify 2>&1 |
    Out-File -Append -Encoding utf8 "logs/health.log"
$code = $LASTEXITCODE
"[$(Get-Date -Format o)] health result: $code" |
    Out-File -Append -Encoding utf8 "logs/health.log"

# Refresh read-only evidence even if campaign health is degraded.
& $uv run python scripts/build_options_evidence.py 2>&1 |
    Out-File -Append -Encoding utf8 "logs/health.log"
& $uv run python scripts/build_options_live_gate.py 2>&1 |
    Out-File -Append -Encoding utf8 "logs/health.log"
& $uv run python scripts/build_readiness.py 2>&1 |
    Out-File -Append -Encoding utf8 "logs/health.log"
& $uv run python scripts/build_decisions.py 2>&1 |
    Out-File -Append -Encoding utf8 "logs/health.log"
& $uv run python scripts/check_testnet_canary.py 2>&1 |
    Out-File -Append -Encoding utf8 "logs/health.log"
$canaryCode = $LASTEXITCODE
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\check_host.ps1 2>&1 |
    Out-File -Append -Encoding utf8 "logs/health.log"

if ($code -eq 0 -and $canaryCode -ne 0) { $code = $canaryCode }
exit $code

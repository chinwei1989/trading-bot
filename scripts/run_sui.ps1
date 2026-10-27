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

$log = "logs/sui.log"
"[$(Get-Date -Format o)] SUI paper start" |
    Out-File -Append -Encoding utf8 $log

& $uv run python -m tradingbot --config config/sui.yaml download 2>&1 |
    Out-File -Append -Encoding utf8 $log
if ($LASTEXITCODE -ne 0) {
    "[$(Get-Date -Format o)] SUI download failed: $LASTEXITCODE" |
        Out-File -Append -Encoding utf8 $log
    exit $LASTEXITCODE
}

# --no-evaluate keeps the isolated SUI run from overwriting the shared
# artifacts/reports/evaluation_trend.json used by the 8-asset campaign.
& $uv run python -m tradingbot --config config/sui.yaml `
    run --mode paper --once --strategy trend --no-evaluate 2>&1 |
    Out-File -Append -Encoding utf8 $log
$code = $LASTEXITCODE
"[$(Get-Date -Format o)] SUI paper result: $code" |
    Out-File -Append -Encoding utf8 $log
exit $code

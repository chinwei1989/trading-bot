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
exit $code

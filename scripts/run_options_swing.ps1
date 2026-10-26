$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
New-Item -ItemType Directory -Force -Path "artifacts/options_swing" | Out-Null

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCommand) {
    $uv = $uvCommand.Source
} elseif (Test-Path "$env:USERPROFILE\.local\bin\uv.exe") {
    $uv = "$env:USERPROFILE\.local\bin\uv.exe"
} else {
    throw "uv not found. Run scripts/bootstrap.ps1 first."
}

"[$(Get-Date -Format o)] options swing cycle start" |
    Out-File -Append -Encoding utf8 "logs/options_swing.log"
& $uv run python -m tradingbot --config config/options_swing.yaml options-swing-run 2>&1 |
    Out-File -Append -Encoding utf8 "logs/options_swing.log"
$code = $LASTEXITCODE
"[$(Get-Date -Format o)] options swing cycle result: $code" |
    Out-File -Append -Encoding utf8 "logs/options_swing.log"
exit $code

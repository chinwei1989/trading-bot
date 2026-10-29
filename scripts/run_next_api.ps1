$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCommand) {
    $uv = $uvCommand.Source
} elseif (Test-Path "$env:USERPROFILE\.local\bin\uv.exe") {
    $uv = "$env:USERPROFILE\.local\bin\uv.exe"
} else {
    throw "uv not found. Run scripts/bootstrap.ps1 first."
}

$decisionSnapshot = Join-Path $root "artifacts\decisions\latest.json"
if (-not (Test-Path $decisionSnapshot)) {
    & $uv run python scripts/build_decisions.py
}

& $uv run uvicorn dashboard_api:app `
    --app-dir scripts `
    --host 127.0.0.1 `
    --port 8000

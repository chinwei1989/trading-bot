param(
    [switch]$Dev
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$apiScript = Join-Path $root "scripts\run_next_api.ps1"
$nextScript = Join-Path $root "scripts\run_next_dashboard.ps1"

$api = $null
$apiListening = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue
if (-not $apiListening) {
    $api = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$apiScript`"" `
        -PassThru `
        -WindowStyle Hidden
    Start-Sleep -Seconds 2
}

try {
    if ($Dev) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $nextScript -Dev
    } else {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $nextScript
    }
} finally {
    if ($api -and -not $api.HasExited) {
        Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue
    }
}

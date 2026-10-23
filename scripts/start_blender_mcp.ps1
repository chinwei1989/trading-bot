$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$blender = "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"
$startScript = Join-Path $root "tools\start_blender_mcp.py"

if (-not (Test-Path $blender)) {
    throw "Blender 4.5 not found at $blender"
}
if (Get-NetTCPConnection -LocalPort 9876 -State Listen -ErrorAction SilentlyContinue) {
    Write-Output "Blender MCP is already listening on localhost:9876."
    exit 0
}
Start-Process -FilePath $blender -ArgumentList @("--python", $startScript)
Start-Sleep -Seconds 6
if (Get-NetTCPConnection -LocalPort 9876 -State Listen -ErrorAction SilentlyContinue) {
    Write-Output "Blender MCP started on localhost:9876."
} else {
    Write-Output "Blender launched, but port 9876 is not listening yet. Check Blender's MCP tab."
}

param(
    [switch]$Dev
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root "frontend"
Set-Location $frontend

$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
    $nodeDir = Split-Path $node.Source
} else {
    $candidate = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" `
        -Recurse -Filter node.exe -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $candidate) {
        throw "Node.js is not installed. Install Node.js LTS and retry."
    }
    $nodeDir = $candidate.DirectoryName
}
$env:Path = "$nodeDir;$env:Path"
$env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:8000"

if ($Dev) {
    & "$nodeDir\npm.cmd" run dev
} else {
    & "$nodeDir\npm.cmd" run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & "$nodeDir\npm.cmd" run start
}

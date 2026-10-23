# Bootstrap the Windows development environment for this project.
# Run from the repo root:
#   powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1

$ErrorActionPreference = "Stop"

Write-Host "== tradingbot bootstrap ==" -ForegroundColor Cyan

# 1. Ensure uv is available.
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    Write-Host "uv not found; installing..." -ForegroundColor Yellow
    try {
        winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements
    } catch {
        Write-Host "winget install failed; using the official installer..." -ForegroundColor Yellow
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    }
    $env:Path = "$env:USERPROFILE\.local\bin;$env:LOCALAPPDATA\Microsoft\WinGet\Links;$env:Path"
    $uv = Get-Command uv -ErrorAction SilentlyContinue
}
if (-not $uv) {
    throw "uv is still not available. Open a new PowerShell and rerun this script."
}
Write-Host ("uv: " + (uv --version))

# 2. Install Python 3.12 and sync dependencies.
uv python install 3.12
uv sync --extra dev

# 3. Create data directories.
$dirs = @(
    "data/raw", "data/normalized", "data/features", "data/reference",
    "artifacts", "logs"
)
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}

# 4. Verify.
uv run python scripts/check_env.py

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Green
Write-Host "  1. Copy .env.example to .env and add paper/testnet API keys."
Write-Host "  2. Read docs/08_BOOTSTRAP.md."
Write-Host "  3. Run: uv run python scripts/check_env.py"

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CanaryArgs
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
New-Item -ItemType Directory -Force -Path "artifacts/ai_options_30m" | Out-Null

$id = [Environment]::GetEnvironmentVariable("DERIBIT_CLIENT_ID", "User")
$secret = [Environment]::GetEnvironmentVariable("DERIBIT_CLIENT_SECRET", "User")
if (-not $id -or -not $secret) {
    throw "Deribit testnet credentials are not set in the Windows user environment."
}
$env:DERIBIT_CLIENT_ID = $id
$env:DERIBIT_CLIENT_SECRET = $secret

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCommand) {
    $uv = $uvCommand.Source
} elseif (Test-Path "$env:USERPROFILE\.local\bin\uv.exe") {
    $uv = "$env:USERPROFILE\.local\bin\uv.exe"
} else {
    throw "uv not found. Run scripts/bootstrap.ps1 first."
}

"[$(Get-Date -Format o)] testnet canary start args=$($CanaryArgs -join ' ')" |
    Out-File -Append -Encoding utf8 "logs/testnet_canary.log"
& $uv run python scripts/run_deribit_testnet_canary.py @CanaryArgs 2>&1 |
    Out-File -Append -Encoding utf8 "logs/testnet_canary.log"
$code = $LASTEXITCODE
"[$(Get-Date -Format o)] testnet canary result: $code" |
    Out-File -Append -Encoding utf8 "logs/testnet_canary.log"

Remove-Item Env:\DERIBIT_CLIENT_ID -ErrorAction SilentlyContinue
Remove-Item Env:\DERIBIT_CLIENT_SECRET -ErrorAction SilentlyContinue
exit $code

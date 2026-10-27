param(
    [ValidateSet("eth", "btc-lab")]
    [string]$Lane = "eth"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force -Path "logs" | Out-Null

$config = if ($Lane -eq "eth") {
    "config/ai_options_eth_paper.yaml"
} else {
    "config/ai_options_btc_lab.yaml"
}
$log = if ($Lane -eq "eth") {
    "logs/ai_options_eth.log"
} else {
    "logs/ai_options_btc_lab.log"
}

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCommand) {
    $uv = $uvCommand.Source
} elseif (Test-Path "$env:USERPROFILE\.local\bin\uv.exe") {
    $uv = "$env:USERPROFILE\.local\bin\uv.exe"
} else {
    throw "uv not found. Run scripts/bootstrap.ps1 first."
}

$cliArgs = @(
    "run", "python", "-m", "tradingbot",
    "--config", $config,
    "ai-options-run"
)

"[$(Get-Date -Format o)] AI options lab start lane=$Lane config=$config" |
    Out-File -Append -Encoding utf8 $log
& $uv @cliArgs 2>&1 | Out-File -Append -Encoding utf8 $log
$code = $LASTEXITCODE
"[$(Get-Date -Format o)] AI options lab result lane=$Lane code=$code" |
    Out-File -Append -Encoding utf8 $log
exit $code

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$StopScript = Join-Path $PSScriptRoot "stop-dev.ps1"
$StartScript = Join-Path $PSScriptRoot "start-dev.ps1"

Write-Host "Reiniciando SlicerApp..." -ForegroundColor Green

& $StopScript
Start-Sleep -Seconds 2
& $StartScript

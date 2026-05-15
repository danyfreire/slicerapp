$ErrorActionPreference = "SilentlyContinue"

$Root = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $Root ".slicerapp-dev-pids.json"

if (Test-Path $PidFile) {
  $pids = Get-Content $PidFile -Raw | ConvertFrom-Json
  foreach ($processId in @($pids.backend_shell_pid, $pids.frontend_shell_pid)) {
    if ($processId) {
      Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
      Write-Host "Detenido proceso SlicerApp $processId"
    }
  }
  Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

function Stop-Port($Port) {
  $lines = netstat -ano | Select-String ":$Port\s+.*LISTENING"
  foreach ($line in $lines) {
    $parts = ($line.ToString().Trim() -split "\s+")
    $processId = [int]$parts[-1]
    if ($processId -gt 0) {
      Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
      Write-Host "Detenido proceso $processId en puerto $Port"
    }
  }
}

3000..3010 | ForEach-Object { Stop-Port $_ }
8000..8020 | ForEach-Object { Stop-Port $_ }

Write-Host "SlicerApp dev detenido."

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"
$PidFile = Join-Path $Root ".slicerapp-dev-pids.json"

function Test-PortBusy($Port) {
  $lines = netstat -ano | Select-String ":$Port\s+.*LISTENING"
  return [bool]$lines
}

function Get-FreePort($PreferredPort) {
  for ($port = $PreferredPort; $port -lt ($PreferredPort + 20); $port++) {
    if (-not (Test-PortBusy $port)) {
      return $port
    }
  }
  throw "No encontré un puerto libre cerca de $PreferredPort."
}

function Get-SystemPython {
  $python = Get-Command python.exe -ErrorAction SilentlyContinue
  if ($python) {
    return $python.Source
  }

  $py = Get-Command py.exe -ErrorAction SilentlyContinue
  if ($py) {
    return $py.Source
  }

  return $null
}

function Test-VenvPython {
  if (-not (Test-Path $Python)) {
    return $false
  }

  & $Python --version *> $null
  return $LASTEXITCODE -eq 0
}

if (-not (Test-VenvPython)) {
  $systemPython = Get-SystemPython
  if (-not $systemPython) {
    Write-Host "No encontré Python instalado en PATH." -ForegroundColor Red
    Write-Host "Instálalo con: winget install Python.Python.3.12"
    exit 1
  }

  $venvPath = Join-Path $Backend ".venv"
  if (Test-Path $venvPath) {
    $backupPath = Join-Path $Backend (".venv.broken-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
    Write-Host "El entorno backend\.venv está roto. Lo moveré a $backupPath" -ForegroundColor Yellow
    Move-Item -Path $venvPath -Destination $backupPath
  }

  Write-Host "Creando entorno virtual del backend..." -ForegroundColor Yellow
  Push-Location $Backend
  try {
    if ((Split-Path -Leaf $systemPython) -ieq "py.exe") {
      & $systemPython -3 -m venv .venv
    }
    else {
      & $systemPython -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) {
      Write-Host "No se pudo crear backend\.venv." -ForegroundColor Red
      exit 1
    }
  }
  finally {
    Pop-Location
  }
}

Push-Location $Backend
try {
  & $Python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('uvicorn') else 1)" *> $null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Instalando dependencias del backend..." -ForegroundColor Yellow
    & $Python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
      Write-Host "No se pudieron instalar las dependencias del backend." -ForegroundColor Red
      exit 1
    }
  }
}
finally {
  Pop-Location
}

Write-Host "Iniciando SlicerApp..." -ForegroundColor Green

$BackendPort = Get-FreePort 8000
if ($BackendPort -ne 8000) {
  Write-Host "El puerto 8000 está ocupado. Usaré backend en http://localhost:$BackendPort" -ForegroundColor Yellow
}

$backendProcess = Start-Process powershell.exe -ArgumentList @(
  "-NoExit",
  "-ExecutionPolicy", "Bypass",
  "-Command",
  "cd '$Backend'; .\.venv\Scripts\python.exe -m uvicorn main:app --reload --port $BackendPort"
) -WindowStyle Normal -PassThru

$frontendProcess = Start-Process powershell.exe -ArgumentList @(
  "-NoExit",
  "-ExecutionPolicy", "Bypass",
  "-Command",
  "cd '$Frontend'; `$env:NEXT_PUBLIC_API_BASE_URL='http://localhost:$BackendPort'; npm.cmd run dev"
) -WindowStyle Normal -PassThru

@{
  backend_shell_pid = $backendProcess.Id
  frontend_shell_pid = $frontendProcess.Id
  backend_port = $BackendPort
  frontend_port = 3000
  started_at = (Get-Date).ToString("s")
} | ConvertTo-Json | Set-Content -Path $PidFile -Encoding UTF8

Write-Host "Backend:  http://localhost:$BackendPort" -ForegroundColor Cyan
Write-Host "Frontend: http://localhost:3000" -ForegroundColor Cyan

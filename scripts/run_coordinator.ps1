# Run coordinator (wave 5). Banner + preflight, then boot uvicorn in FOREGROUND.
# Usage: .\scripts\run_coordinator.ps1
$ErrorActionPreference = "Stop"
$Port = 8000
$Role = "coordinator"
$LogPath = "logs\coord-8000.log"

Write-Host "===============================================" -ForegroundColor Cyan
Write-Host " RAID1 $Role : port $Port" -ForegroundColor Cyan
Write-Host " Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
if (Test-Path .\.env) {
  $shown = Get-Content .\.env | Where-Object { $_ -match '^(NODES|COORDINATOR_URL)=' }
  foreach ($line in $shown) { Write-Host " .env: $line" }
} else {
  Write-Host " .env: (missing)"
}
try {
  $tsIp = (tailscale ip -4 2>$null | Select-Object -First 1)
  if ($tsIp) { Write-Host " Tailscale IPv4: $($tsIp.ToString().Trim())" }
  else { Write-Host " Tailscale IPv4: (not available - tailscale ip -4 returned nothing)" -ForegroundColor Yellow }
} catch {
  Write-Host " Tailscale IPv4: (not available - tailscale not installed or not logged in)" -ForegroundColor Yellow
}
Write-Host " Log: $LogPath" -ForegroundColor Green
Write-Host "===============================================" -ForegroundColor Cyan

if (-not (Test-Path .\.venv\Scripts\Activate.ps1)) {
  Write-Host "PREFLIGHT FAIL: .venv not found. Fix: python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt" -ForegroundColor Red
  exit 1
}
if (-not (Test-Path .\.env)) {
  Write-Host "PREFLIGHT FAIL: .env not found. Fix: create .env with COORDINATOR_URL, NODES and X_INTERNAL_KEY (see README), then retry." -ForegroundColor Red
  exit 1
}
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($busy) {
  Write-Host "PREFLIGHT FAIL: port $Port busy (owning PID $($busy.OwningProcess)). Fix: stop that process (Stop-Process -Id $($busy.OwningProcess)) or free the port, then retry." -ForegroundColor Red
  exit 1
}

if (-not (Test-Path logs)) { New-Item -ItemType Directory -Path logs | Out-Null }
# Load .env into process env for the uvicorn child (existing env wins).
# Sin esto, os.getenv("X_INTERNAL_KEY"/"X_API_KEY") queda vacio en el
# coordinador y toda validacion falla con 403 aunque los nodos envien bien.
$envFile = @{}
if (Test-Path .\.env) {
  foreach ($line in Get-Content .\.env) {
    $t = $line.Trim()
    if (-not $t -or $t.StartsWith('#')) { continue }
    $i = $t.IndexOf('=')
    if ($i -lt 1) { continue }
    $k = $t.Substring(0, $i).Trim()
    $v = $t.Substring($i + 1).Trim().Trim('"').Trim("'")
    if ($k) { $envFile[$k] = $v }
  }
}
foreach ($k in $envFile.Keys) {
  if (-not (Test-Path "env:$k")) { Set-Item -Path "env:$k" -Value $envFile[$k] }
}
if (Test-Path .\.venv\Scripts\Activate.ps1) { . .\.venv\Scripts\Activate.ps1 }
# uvicorn logs INFO to stderr: relax to Continue so log lines don't raise NativeCommandError.
$ErrorActionPreference = "Continue"
# Stringify ErrorRecords so stderr lines print/log as clean text (no CategoryInfo dumps).
# Sin --reload: un solo proceso (igual que run_coordinator.sh y run_node.ps1).
# Con --reload uvicorn reinicia el coordinador ante CUALQUIER cambio
# (logs/, *.db, frontend/, data-node-*/), la consola parece recargarse
# en bucle y se pierden conexiones/listados en pleno uso.
uvicorn coordinator.app.main:app --host 0.0.0.0 --port $Port 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $LogPath -Append

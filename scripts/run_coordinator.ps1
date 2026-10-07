# Run coordinator (wave 5). Banner + preflight, then boot uvicorn in FOREGROUND.
# Usage: .\scripts\run_coordinator.ps1
$ErrorActionPreference = "Stop"
$Port = 8000
$Role = "coordinator"
$LogPath = "logs\coord-8000.log"

Write-Host "==============================================="
Write-Host " RAID1 $Role : port $Port"
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
  else { Write-Host " Tailscale IPv4: (not available - tailscale ip -4 returned nothing)" }
} catch {
  Write-Host " Tailscale IPv4: (not available - tailscale not installed or not logged in)"
}
Write-Host " Log: $LogPath"
Write-Host "==============================================="

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
if (Test-Path .\.venv\Scripts\Activate.ps1) { . .\.venv\Scripts\Activate.ps1 }
uvicorn coordinator.app.main:app --host 0.0.0.0 --port $Port --reload 2>&1 | Tee-Object -FilePath $LogPath -Append

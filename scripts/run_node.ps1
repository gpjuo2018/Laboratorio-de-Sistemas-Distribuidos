# Run a storage node (unified entrypoint): boots uvicorn in BACKGROUND,
# waits until /internal/health is ready, then runs the enriched heartbeat
# loop in FOREGROUND. Ctrl+C stops the loop AND the node process.
# Usage: .\scripts\run_node.ps1 -NodeId node-1 -Port 8001 [-CoordinatorUrl http://127.0.0.1:8000] [-IntervalSecs 10]
param(
  [string]$NodeId = $(if ($env:NODE_ID) { $env:NODE_ID } else { "node-1" }),
  [int]$Port = 8001,
  [string]$CoordinatorUrl = $(if ($env:COORDINATOR_URL) { $env:COORDINATOR_URL } else { "http://127.0.0.1:8000" }),
  [int]$IntervalSecs = 10
)
$ErrorActionPreference = "Stop"
$Role = "node"
$LogPath = "logs\node-$NodeId-$Port.log"
$LocalBase = "http://127.0.0.1:$Port"

Write-Host "==============================================="
Write-Host " RAID1 $Role : $NodeId on port $Port"
Write-Host " Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host " NODE_ID: $NodeId"
Write-Host " Coordinator: $CoordinatorUrl (beat every ${IntervalSecs}s)"
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
$env:NODE_ID = $NodeId
$env:NODE_PORT = "$Port"

$python = Join-Path (Get-Location) ".venv\Scripts\python.exe"
$nodeProc = Start-Process -FilePath $python -ArgumentList @("-m", "uvicorn", "node.app.main:app", "--host", "0.0.0.0", "--port", "$Port", "--reload") -RedirectStandardOutput $LogPath -RedirectStandardError $LogPath -PassThru
Write-Host "Booting node $NodeId on port $Port (PID $($nodeProc.Id)), waiting for /internal/health ..."
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
  Start-Sleep -Seconds 1
  if ($nodeProc.HasExited) { break }
  try {
    $probe = Invoke-RestMethod -Uri "$LocalBase/internal/health" -TimeoutSec 2
    if ($probe.status -eq "ok") { $ready = $true; break }
  } catch {
  }
}
if (-not $ready) {
  Write-Host "NODE FAIL: $NodeId never became ready within ~20s. Tail of $LogPath :" -ForegroundColor Red
  if (Test-Path $LogPath) { Get-Content $LogPath -Tail 20 }
  if (-not $nodeProc.HasExited) { Stop-Process -Id $nodeProc.Id -Force }
  exit 1
}

Write-Host "node up, starting heartbeat: node=$NodeId local=$LocalBase coord=$CoordinatorUrl every=${IntervalSecs}s (Ctrl+C stops node + loop)"
try {
  while ($true) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    try {
      $health = Invoke-RestMethod -Uri "$LocalBase/internal/health" -TimeoutSec 5
    } catch {
      Write-Host "$stamp beat transient-error node=$NodeId local health unreachable: $($_.Exception.Message)"
      Start-Sleep -Seconds $IntervalSecs
      continue
    }
    $body = @{
      node_id      = $NodeId
      disk_free    = $health.disk_free
      files_stored = $health.files_stored
      uptime_secs  = $health.uptime_secs
      version      = $health.version
    } | ConvertTo-Json
    try {
      Invoke-RestMethod -Method Post -Uri "$CoordinatorUrl/nodes/heartbeat" -Body $body -ContentType "application/json" -TimeoutSec 5 | Out-Null
      Write-Host "$stamp beat ok node=$NodeId files=$($health.files_stored) up=$([math]::Round($health.uptime_secs, 1))s ver=$($health.version)"
    } catch {
      Write-Host "$stamp beat dead-coordinator node=$NodeId coord=$CoordinatorUrl err=$($_.Exception.Message)"
    }
    Start-Sleep -Seconds $IntervalSecs
  }
} finally {
  if (-not $nodeProc.HasExited) { Stop-Process -Id $nodeProc.Id -Force }
  Write-Host "stopped node $NodeId (PID $($nodeProc.Id))."
}

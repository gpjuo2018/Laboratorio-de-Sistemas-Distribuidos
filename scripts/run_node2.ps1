# LOCAL FIX - no subir a GitHub. Copia mejorada de scripts/run_node.ps1.
#
# Correcciones sobre el original (bug del commit 5a1e1b8):
# 1. Start-Process no permite -RedirectStandardOutput y -RedirectStandardError
#    apuntando al MISMO archivo (InvalidOperationException "son iguales").
#    Fix: stdout -> logs\node-<id>-<port>.log | stderr -> logs\node-<id>-<port>-err.log
# 2. El original NO lee .env (solo lo mostraba en el banner) y arrancaba como
#    node-1:8001 contra 127.0.0.1:8000. Fix: .env carga NODE_ID/NODE_PORT/
#    COORDINATOR_URL (los params -NodeId/-Port/-CoordinatorUrl ganan si se pasan).
# 3. El coordinador devuelve 404 "unknown node, register first" en /nodes/heartbeat
#    si el nodo no se registró. Fix: POST /nodes/register antes del loop (sin auth,
#    upsert - es el flujo normal de un nodo entrante) y re-registro automatico si
#    un heartbeat responde 404.
#
# Cuando run_node.ps1 oficial se arregle en GitHub: borrar este archivo y usarlo.
#
# Run a storage node (unified entrypoint): boots uvicorn in BACKGROUND,
# waits until /internal/health is ready, then registers + runs the enriched
# heartbeat loop in FOREGROUND. Ctrl+C stops the loop AND the node process.
# Usage: .\scripts\run_node_local.ps1            (lee todo de .env)
#        .\scripts\run_node_local.ps1 -NodeId nodo2 -Port 8002 [-CoordinatorUrl http://ip:8000] [-IntervalSecs 10]
param(
  [string]$NodeId = $(if ($env:NODE_ID) { $env:NODE_ID } else { "node-1" }),
  [int]$Port = 8001,
  [string]$CoordinatorUrl = $(if ($env:COORDINATOR_URL) { $env:COORDINATOR_URL } else { "http://127.0.0.1:8000" }),
  [int]$IntervalSecs = 10
)
$ErrorActionPreference = "Stop"

# --- Load .env (params explicitly passed via command line win over it) --------
$envFile = @{}
if (Test-Path .\.env) {
  foreach ($line in Get-Content .\.env) {
    $t = $line.Trim()
    if (-not $t -or $t.StartsWith('#')) { continue }
    $i = $t.IndexOf('=')
    if ($i -lt 1) { continue }
    $envFile[$t.Substring(0, $i).Trim()] = $t.Substring($i + 1).Trim()
  }
}
if (-not $PSBoundParameters.ContainsKey('NodeId') -and $envFile['NODE_ID']) { $NodeId = $envFile['NODE_ID'] }
if (-not $PSBoundParameters.ContainsKey('Port')) {
  $p = $envFile['NODE_PORT'] -as [int]
  if ($p) { $Port = $p }
}
if (-not $PSBoundParameters.ContainsKey('CoordinatorUrl') -and $envFile['COORDINATOR_URL']) { $CoordinatorUrl = $envFile['COORDINATOR_URL'] }

$Role = "node"
$LogPath = "logs\node-$NodeId-$Port.log"
$ErrLogPath = "logs\node-$NodeId-$Port-err.log"
$LocalBase = "http://127.0.0.1:$Port"

Write-Host "==============================================="
Write-Host " RAID1 $Role : $NodeId on port $Port"
Write-Host " Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host " NODE_ID: $NodeId"
Write-Host " Coordinator: $CoordinatorUrl (beat every ${IntervalSecs}s)"
if ($envFile.Count -gt 0) {
  foreach ($k in @('NODE_ID', 'NODE_PORT', 'COORDINATOR_URL')) {
    if ($envFile[$k]) { Write-Host " .env: $k=$($envFile[$k])" }
  }
} else {
  Write-Host " .env: (missing)"
}
$tsIp = $null
try {
  $tsIp = (tailscale ip -4 2>$null | Select-Object -First 1)
  if ($tsIp) { Write-Host " Tailscale IPv4: $($tsIp.ToString().Trim())" }
  else { Write-Host " Tailscale IPv4: (not available - tailscale ip -4 returned nothing)" }
} catch {
  Write-Host " Tailscale IPv4: (not available - tailscale not installed or not logged in)"
}
Write-Host " Log (stdout): $LogPath"
Write-Host " Log (stderr/uvicorn): $ErrLogPath"
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
# Export .env to the process env for the uvicorn child (existing env wins).
foreach ($k in $envFile.Keys) {
  if (-not (Test-Path "env:$k")) { Set-Item -Path "env:$k" -Value $envFile[$k] }
}
if (Test-Path .\.venv\Scripts\Activate.ps1) { . .\.venv\Scripts\Activate.ps1 }
# Resolved values always win for the node identity (child + heartbeat loop).
$env:NODE_ID = $NodeId
$env:NODE_PORT = "$Port"
$env:COORDINATOR_URL = $CoordinatorUrl

# Node base_url advertised to the coordinator (it must reach us: tailnet IP).
$BaseUrl = if ($tsIp) { "http://$(($tsIp.ToString().Trim())):$Port" } else { "http://127.0.0.1:$Port" }

function Register-NodeOnce {
  $body = @{ node_id = $NodeId; base_url = $BaseUrl }
  try {
    $h = Invoke-RestMethod -Uri "$LocalBase/internal/health" -TimeoutSec 3
    $body += @{ disk_free = $h.disk_free; files_stored = $h.files_stored; uptime_secs = $h.uptime_secs; version = $h.version }
  } catch { }
  try {
    Invoke-RestMethod -Method Post -Uri "$CoordinatorUrl/nodes/register" -Body ($body | ConvertTo-Json) -ContentType "application/json" -TimeoutSec 5 | Out-Null
    Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') registered node=$NodeId base=$BaseUrl coord=$CoordinatorUrl"
    return $true
  } catch {
    Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') register pending node=$NodeId coord=$CoordinatorUrl err=$($_.Exception.Message) (will retry on next beat)" -ForegroundColor Yellow
    return $false
  }
}

$python = Join-Path (Get-Location) ".venv\Scripts\python.exe"
$nodeProc = Start-Process -FilePath $python -ArgumentList @("-m", "uvicorn", "node.app.main:app", "--host", "0.0.0.0", "--port", "$Port", "--reload") -RedirectStandardOutput $LogPath -RedirectStandardError $ErrLogPath -PassThru
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
  Write-Host "NODE FAIL: $NodeId never became ready within ~20s. Tail of $ErrLogPath :" -ForegroundColor Red
  if (Test-Path $ErrLogPath) { Get-Content $ErrLogPath -Tail 20 }
  if (Test-Path $LogPath) { Get-Content $LogPath -Tail 5 }
  if (-not $nodeProc.HasExited) { Stop-Process -Id $nodeProc.Id -Force }
  exit 1
}

Register-NodeOnce | Out-Null

Write-Host "node up, starting heartbeat: node=$NodeId local=$LocalBase base=$BaseUrl coord=$CoordinatorUrl every=${IntervalSecs}s (Ctrl+C stops node + loop)"
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
      $msg = $_.Exception.Message
      if ($msg -match '404') {
        # Coordinator doesn't know us (fresh DB / restarted): register and let the next beat land.
        Write-Host "$stamp beat node=$NodeId rejected (404) -> re-registering with coordinator" -ForegroundColor Yellow
        Register-NodeOnce | Out-Null
      } else {
        Write-Host "$stamp beat dead-coordinator node=$NodeId coord=$CoordinatorUrl err=$msg"
      }
    }
    Start-Sleep -Seconds $IntervalSecs
  }
} finally {
  if (-not $nodeProc.HasExited) { Stop-Process -Id $nodeProc.Id -Force }
  Write-Host "stopped node $NodeId (PID $($nodeProc.Id))."
}

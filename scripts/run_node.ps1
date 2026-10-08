# Run a storage node (unified entrypoint): boots uvicorn in BACKGROUND,
# waits until /internal/health is ready, registers + runs the enriched
# heartbeat loop in FOREGROUND. Ctrl+C stops the loop AND the node process.
#
# GENERICO: sin argumentos lee todo de .env (NODE_ID, NODE_PORT o inferencia
# desde NODES, COORDINATOR_URL, HEARTBEAT_INTERVAL, DATA_DIR). Cada companero
# solo edita su .env y ejecuta: .\scripts\run_node.ps1
#
# Usage: .\scripts\run_node.ps1                                        (todo de .env)
#        .\scripts\run_node.ps1 -NodeId node-2                         (puerto inferido de NODES[1])
#        .\scripts\run_node.ps1 -NodeId node-2 -Port 8002 [-CoordinatorUrl http://<ip-coord>:8000] [-IntervalSecs 10]
param(
  [string]$NodeId = $(if ($env:NODE_ID) { $env:NODE_ID } else { "node-1" }),
  [int]$Port = 8001,
  [string]$CoordinatorUrl = $(if ($env:COORDINATOR_URL) { $env:COORDINATOR_URL } else { "http://127.0.0.1:8000" }),
  [int]$IntervalSecs = 10
)
$ErrorActionPreference = "Stop"

# --- Load .env (explicit CLI params win over it) -----------------------------
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

$NodeIdExplicit = $PSBoundParameters.ContainsKey('NodeId')
$PortExplicit = $PSBoundParameters.ContainsKey('Port')
$CoordExplicit = $PSBoundParameters.ContainsKey('CoordinatorUrl')
$IntervalExplicit = $PSBoundParameters.ContainsKey('IntervalSecs')

# NodeId: CLI > .env NODE_ID > process env / default (ya evaluado en param).
$NodeIdSource = "default/param"
if (-not $NodeIdExplicit -and $envFile['NODE_ID']) {
  $NodeId = $envFile['NODE_ID']
  $NodeIdSource = ".env NODE_ID"
} elseif ($NodeIdExplicit) {
  $NodeIdSource = "CLI -NodeId"
} elseif ($env:NODE_ID) {
  $NodeIdSource = "env NODE_ID"
}

# Port: CLI > .env NODE_PORT (solo si el NodeId coincide con el del .env,
# para no atar al nodo-2 al puerto del coordinador u otro nodo) > inferencia
# desde NODES por indice (node-1->NODES[0], node-2->NODES[1], ...) > 8000+N.
$PortSource = "default 8001"
if (-not $PortExplicit) {
  $envPort = 0
  try { $envPort = [int]$envFile['NODE_PORT'] } catch { $envPort = 0 }
  $envNodeId = $envFile['NODE_ID']
  if ($envPort -ge 1 -and $envPort -le 65535 -and (-not $envNodeId -or $envNodeId -eq $NodeId)) {
    $Port = $envPort
    $PortSource = ".env NODE_PORT"
  } else {
    $inferred = 0
    $num = 0
    if ($NodeId -match '(\d+)\s*$') { $num = [int]$Matches[1] }
    $nodesRaw = $envFile['NODES']
    $nodesList = @()
    if ($nodesRaw) { $nodesList = @($nodesRaw.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
    if ($num -ge 1 -and $num -le $nodesList.Count) {
      $cand = $nodesList[$num - 1]
      $m = [regex]::Match($cand, ':(\d+)(/|$)')
      if ($m.Success) {
        $inferred = [int]$m.Groups[1].Value
        $Port = $inferred
        $PortSource = "NODES[$($num - 1)] ($cand)"
      }
    }
    if ($inferred -eq 0 -and $num -ge 1) {
      $Port = 8000 + $num
      $PortSource = "convencion 8000+N (node-N)"
    }
  }
} else {
  $PortSource = "CLI -Port"
}

# CoordinatorUrl: CLI > .env COORDINATOR_URL > default.
$CoordSource = "default"
if (-not $CoordExplicit -and $envFile['COORDINATOR_URL']) {
  $CoordinatorUrl = $envFile['COORDINATOR_URL']
  $CoordSource = ".env COORDINATOR_URL"
} elseif ($CoordExplicit) {
  $CoordSource = "CLI -CoordinatorUrl"
} elseif ($env:COORDINATOR_URL) {
  $CoordSource = "env COORDINATOR_URL"
}

# IntervalSecs: CLI > .env HEARTBEAT_INTERVAL (o INTERVAL_SECS) > 10.
if (-not $IntervalExplicit) {
  foreach ($k in @('HEARTBEAT_INTERVAL', 'INTERVAL_SECS')) {
    $iv = 0
    try { $iv = [int]$envFile[$k] } catch { $iv = 0 }
    if ($iv -gt 0) { $IntervalSecs = $iv; break }
  }
}

# DATA_DIR: CLI no existe -> .env DATA_DIR, pero si es generico (./data) y el
# nodo no es node-1, aislar a ./data-<nodeid> para no pisar bloques locales.
$DataDir = $envFile['DATA_DIR']
$DataDirSource = ".env DATA_DIR"
if (-not $DataDir) {
  if ($NodeId -eq 'node-1') { $DataDir = './data' } else { $DataDir = "./data-$NodeId" }
  $DataDirSource = "convencion ./data-<nodeid>"
} elseif ($DataDir -match '^(./data|\.\\data|data)$' -and $NodeId -ne 'node-1') {
  $DataDir = "./data-$NodeId"
  $DataDirSource = "aislado de ./data generico -> ./data-<nodeid>"
}

$Role = "node"
$LogPath = "logs\node-$NodeId-$Port.log"
$ErrLogPath = "logs\node-$NodeId-$Port-err.log"
$LocalBase = "http://127.0.0.1:$Port"

Write-Host "==============================================="
Write-Host " RAID1 $Role : $NodeId on port $Port"
Write-Host " Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host " NODE_ID: $NodeId ($NodeIdSource)"
Write-Host " Port: $Port ($PortSource)"
Write-Host " Coordinator: $CoordinatorUrl ($CoordSource) (beat every ${IntervalSecs}s)"
Write-Host " DATA_DIR: $DataDir ($DataDirSource)"
if ($envFile.Count -gt 0) {
  foreach ($k in @('NODE_ID', 'NODE_PORT', 'COORDINATOR_URL', 'DATA_DIR', 'NODES')) {
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
if (-not (Test-Path $DataDir)) { New-Item -ItemType Directory -Path $DataDir | Out-Null }
# Export .env to the process env for the uvicorn child (existing env wins).
foreach ($k in $envFile.Keys) {
  if (-not (Test-Path "env:$k")) { Set-Item -Path "env:$k" -Value $envFile[$k] }
}
if (Test-Path .\.venv\Scripts\Activate.ps1) { . .\.venv\Scripts\Activate.ps1 }
# Resolved values always win for the node identity (child + heartbeat loop).
$env:NODE_ID = $NodeId
$env:NODE_PORT = "$Port"
$env:COORDINATOR_URL = $CoordinatorUrl
$env:DATA_DIR = $DataDir

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
# NOTA: stdout y stderr NO pueden ir al mismo archivo (Start-Process lo prohibe).
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

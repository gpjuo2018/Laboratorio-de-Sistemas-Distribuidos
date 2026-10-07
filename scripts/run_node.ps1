# Run a storage node (skeleton). Activate venv then boot uvicorn.
# Usage: .\scripts\run_node.ps1 -NodeId node-1 -Port 8001
param([string]$NodeId = "node-1", [int]$Port = 8001)
if (Test-Path .\.venv\Scripts\Activate.ps1) { . .\.venv\Scripts\Activate.ps1 }
$env:NODE_ID = $NodeId
uvicorn node.app.main:app --host 0.0.0.0 --port $Port --reload

# Run coordinator (skeleton). Activate venv then boot uvicorn.
# Usage: .\scripts\run_coordinator.ps1
if (Test-Path .\.venv\Scripts\Activate.ps1) { . .\.venv\Scripts\Activate.ps1 }
uvicorn coordinator.app.main:app --host 0.0.0.0 --port 8000 --reload

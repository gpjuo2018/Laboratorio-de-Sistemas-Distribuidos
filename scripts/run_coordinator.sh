#!/usr/bin/env bash
# Run the coordinator on macOS/Linux (generic entrypoint): loads .env,
# preflight checks, then boots uvicorn in FOREGROUND. Ctrl+C stops it.
#
# Uso: ./scripts/run_coordinator.sh
# Lee COORDINATOR_URL, NODES, X_INTERNAL_KEY y X_API_KEY de .env y los
# exporta al proceso hijo (el entorno existente tiene prioridad).
set -euo pipefail
cd "$(dirname "$0")/.."

PORT=8000
LOG_PATH="logs/coord-8000.log"

if [ ! -f .env ]; then echo "PREFLIGHT FAIL: .env not found"; exit 1; fi
# Load .env without overwriting CLI-provided env (existing env wins).
while IFS='=' read -r k v; do
  k="$(echo "$k" | tr -d '[:space:]')"
  case "$k" in ''|\#*) continue ;; esac
  v="$(echo "$v" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e "s/^['\"]//" -e "s/['\"]$//")"
  if [ -z "${!k:-}" ]; then export "$k=$v"; fi
done < .env

if [ ! -x .venv/bin/python ]; then
  echo "PREFLIGHT FAIL: .venv not found. Fix: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"; exit 1
fi
if command -v lsof >/dev/null 2>&1; then
  if lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "PREFLIGHT FAIL: port $PORT busy. Fix: lsof -iTCP:$PORT -sTCP:LISTEN, luego kill <PID>"; exit 1
  fi
fi

echo "==============================================="
echo " RAID1 coordinator : port $PORT"
echo " COORDINATOR_URL: ${COORDINATOR_URL:-http://127.0.0.1:8000}"
echo " Log: $LOG_PATH"
echo "==============================================="

mkdir -p logs
# Foreground a proposito: Ctrl+C o cierre de terminal libera el puerto.
# Sin --reload: un solo proceso python.
trap 'echo "stopped coordinator."' EXIT HUP INT TERM
.venv/bin/python -m uvicorn coordinator.app.main:app --host 0.0.0.0 --port "$PORT" 2>&1 | tee -a "$LOG_PATH"

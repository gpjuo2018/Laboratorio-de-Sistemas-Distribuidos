#!/usr/bin/env bash
# Run a storage node on macOS/Linux: loads .env, boots uvicorn in BACKGROUND,
# waits for /internal/health, then runs the enriched heartbeat loop in FOREGROUND.
# Ctrl+C stops the loop AND the node process.
# Usage: ./scripts/run_node.sh [NODE_ID] [PORT]
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then echo "PREFLIGHT FAIL: .env not found"; exit 1; fi
set -a; . ./.env; set +a

NODE_ID="${1:-${NODE_ID:-node-1}}"
NODE_PORT="${2:-${NODE_PORT:-8001}}"
COORDINATOR_URL="${COORDINATOR_URL:-http://127.0.0.1:8000}"
INTERVAL_SECS="${INTERVAL_SECS:-10}"
export NODE_ID NODE_PORT
LOCAL_BASE="http://127.0.0.1:$NODE_PORT"
LOG_PATH="logs/node-$NODE_ID-$NODE_PORT.log"

if [ ! -x .venv/bin/python ]; then
  echo "PREFLIGHT FAIL: .venv not found. Fix: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"; exit 1
fi
if lsof -iTCP:"$NODE_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "PREFLIGHT FAIL: port $NODE_PORT busy"; exit 1
fi

echo "==============================================="
echo " RAID1 node : $NODE_ID on port $NODE_PORT"
echo " Coordinator: $COORDINATOR_URL (beat every ${INTERVAL_SECS}s)"
echo " Tailscale IPv4: $(tailscale ip -4 2>/dev/null | head -1 || echo n/a)"
echo " Log: $LOG_PATH"
echo "==============================================="

mkdir -p logs "${DATA_DIR:-./data}"
.venv/bin/python -m uvicorn node.app.main:app --host 0.0.0.0 --port "$NODE_PORT" >>"$LOG_PATH" 2>&1 &
NODE_PID=$!
trap 'kill $NODE_PID 2>/dev/null; echo "stopped node $NODE_ID (PID $NODE_PID)."' EXIT

for _ in $(seq 1 20); do
  sleep 1
  if curl -fs "$LOCAL_BASE/internal/health" >/dev/null 2>&1; then READY=1; break; fi
done
if [ -z "${READY:-}" ]; then echo "NODE FAIL: never became ready. Tail of $LOG_PATH:"; tail -20 "$LOG_PATH"; exit 1; fi

echo "node up, heartbeating to $COORDINATOR_URL (Ctrl+C stops node + loop)"
while true; do
  STAMP="$(date '+%Y-%m-%d %H:%M:%S')"
  if ! HEALTH="$(curl -fs --max-time 5 "$LOCAL_BASE/internal/health")"; then
    echo "$STAMP beat transient-error node=$NODE_ID local health unreachable"
    sleep "$INTERVAL_SECS"; continue
  fi
  BODY="$(NODE_ID="$NODE_ID" .venv/bin/python -c '
import json, os, sys
h = json.load(sys.stdin)
print(json.dumps({"node_id": os.environ["NODE_ID"], **{k: h.get(k) for k in ("disk_free", "files_stored", "uptime_secs", "version")}}))
' <<<"$HEALTH")"
  if curl -fs --max-time 5 -X POST "$COORDINATOR_URL/nodes/heartbeat" -H "Content-Type: application/json" -d "$BODY" >/dev/null; then
    echo "$STAMP beat ok node=$NODE_ID"
  else
    echo "$STAMP beat dead-coordinator node=$NODE_ID coord=$COORDINATOR_URL"
  fi
  sleep "$INTERVAL_SECS"
done

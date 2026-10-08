#!/usr/bin/env bash
# Run a storage node on macOS/Linux (generic entrypoint): loads .env,
# boots uvicorn in BACKGROUND, waits for /internal/health, registers +
# runs the enriched heartbeat loop in FOREGROUND. Ctrl+C stops both.
#
# GENERICO: sin argumentos lee todo de .env (NODE_ID, NODE_PORT o inferencia
# desde NODES, COORDINATOR_URL, HEARTBEAT_INTERVAL, DATA_DIR). Cada persona
# solo edita su .env y ejecuta: ./scripts/run_node.sh
#
# Usage: ./scripts/run_node.sh                (todo de .env)
#        ./scripts/run_node.sh node-2         (puerto inferido de NODES[1])
#        ./scripts/run_node.sh node-2 8002 [http://<ip-coord>:8000] [10]
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then echo "PREFLIGHT FAIL: .env not found"; exit 1; fi
# Load .env without overwriting CLI-provided env (existing env wins).
while IFS='=' read -r k v; do
  k="$(echo "$k" | tr -d '[:space:]')"
  case "$k" in ''|\#*) continue ;; esac
  v="$(echo "$v" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e "s/^['\"]//" -e "s/['\"]$//")"
  if [ -z "${!k:-}" ]; then export "$k=$v"; fi
done < .env

CLI_NODE_ID="${1:-}"
CLI_PORT="${2:-}"
CLI_COORD="${3:-}"
CLI_INTERVAL="${4:-}"

# NodeId: CLI > .env NODE_ID > node-1.
if [ -n "$CLI_NODE_ID" ]; then NODE_ID="$CLI_NODE_ID"; SRC_ID="CLI arg1";
elif [ -n "${NODE_ID:-}" ]; then SRC_ID=".env NODE_ID";
else NODE_ID="node-1"; SRC_ID="default node-1"; fi

# Port: CLI > .env NODE_PORT (solo si el NodeId coincide con el del .env)
# > inferencia desde NODES por indice (node-1->NODES[0], ...) > 8000+N.
ENV_NODE_ID="$(grep -E '^NODE_ID=' .env 2>/dev/null | cut -d= -f2 | tr -d '[:space:]'"'"'"' || true)"
ENV_NODE_PORT="$(grep -E '^NODE_PORT=' .env 2>/dev/null | cut -d= -f2 | tr -d '[:space:]'"'"'"' || true)"
if [ -n "$CLI_PORT" ]; then NODE_PORT="$CLI_PORT"; SRC_PORT="CLI arg2";
elif [ -n "${ENV_NODE_PORT:-}" ] && { [ -z "${ENV_NODE_ID:-}" ] || [ "$ENV_NODE_ID" = "$NODE_ID" ]; }; then
  NODE_PORT="$ENV_NODE_PORT"; SRC_PORT=".env NODE_PORT";
else
  NUM="$(echo "$NODE_ID" | grep -oE '[0-9]+[[:space:]]*$' | tr -d '[:space:]' || true)"
  [ -z "$NUM" ] && NUM=1
  IDX=$((NUM - 1))
  INFERRED=""
  if [ -n "${NODES:-}" ]; then
    IFS=',' read -ra _NODES <<< "$NODES"
    if [ "$IDX" -ge 0 ] && [ "$IDX" -lt "${#_NODES[@]}" ]; then
      CAND="$(echo "${_NODES[$IDX]}" | tr -d '[:space:]')"
      INFERRED="$(echo "$CAND" | grep -oE ':[0-9]+' | head -1 | tr -d ':' || true)"
      if [ -n "$INFERRED" ]; then NODE_PORT="$INFERRED"; SRC_PORT="NODES[$IDX] ($CAND)"; fi
    fi
  fi
  if [ -z "${INFERRED:-}" ]; then NODE_PORT=$((8000 + NUM)); SRC_PORT="convencion 8000+N"; fi
fi

# CoordinatorUrl: CLI > .env > localhost.
if [ -n "$CLI_COORD" ]; then COORDINATOR_URL="$CLI_COORD"; SRC_COORD="CLI arg3";
elif [ -n "${COORDINATOR_URL:-}" ]; then SRC_COORD=".env COORDINATOR_URL";
else COORDINATOR_URL="http://127.0.0.1:8000"; SRC_COORD="default"; fi

# Interval: CLI > .env HEARTBEAT_INTERVAL/INTERVAL_SECS > 10.
if [ -n "$CLI_INTERVAL" ]; then INTERVAL_SECS="$CLI_INTERVAL";
elif [ -n "${HEARTBEAT_INTERVAL:-}" ]; then INTERVAL_SECS="$HEARTBEAT_INTERVAL";
elif [ -n "${INTERVAL_SECS:-}" ]; then INTERVAL_SECS="$INTERVAL_SECS";
else INTERVAL_SECS=10; fi

# DATA_DIR: .env, pero si es generico (./data) y no es node-1 -> ./data-<nodeid>.
if [ -z "${DATA_DIR:-}" ]; then
  if [ "$NODE_ID" = "node-1" ]; then DATA_DIR="./data"; else DATA_DIR="./data-$NODE_ID"; fi
  SRC_DATA="convencion ./data-<nodeid>"
elif [ "$DATA_DIR" = "./data" ] && [ "$NODE_ID" != "node-1" ]; then
  DATA_DIR="./data-$NODE_ID"; SRC_DATA="aislado de ./data generico"
else SRC_DATA=".env DATA_DIR"; fi

export NODE_ID NODE_PORT COORDINATOR_URL DATA_DIR
LOCAL_BASE="http://127.0.0.1:$NODE_PORT"
LOG_PATH="logs/node-$NODE_ID-$NODE_PORT.log"

if [ ! -x .venv/bin/python ]; then
  echo "PREFLIGHT FAIL: .venv not found. Fix: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"; exit 1
fi
if command -v lsof >/dev/null 2>&1; then
  # Auto-limpieza: si el puerto lo retiene un nodo anterior (huerfano por
  # cerrar la terminal en vez de Ctrl+C), matarlo y seguir. Otro programa -> FAIL.
  STALE_PID="$(lsof -t -iTCP:"$NODE_PORT" -sTCP:LISTEN 2>/dev/null | head -1 || true)"
  if [ -n "${STALE_PID:-}" ]; then
    STALE_CMD="$(ps -p "$STALE_PID" -o command= 2>/dev/null || true)"
    case "$STALE_CMD" in
      *uvicorn*|*node.app.main*)
        echo "STALE NODE: port $NODE_PORT ocupado por un nodo anterior (PID $STALE_PID). Limpiando..."
        kill -9 "$STALE_PID" 2>/dev/null || true
        sleep 2
        ;;
    esac
  fi
  if lsof -iTCP:"$NODE_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "PREFLIGHT FAIL: port $NODE_PORT busy (no es un nodo). Fix: lsof -iTCP:$NODE_PORT -sTCP:LISTEN, luego kill <PID>"; exit 1
  fi
fi

TS_IP="$(tailscale ip -4 2>/dev/null | head -1 || true)"
echo "==============================================="
echo " RAID1 node : $NODE_ID on port $NODE_PORT"
echo " NODE_ID source: $SRC_ID | Port source: $SRC_PORT | Coord source: $SRC_COORD"
echo " Coordinator: $COORDINATOR_URL (beat every ${INTERVAL_SECS}s)"
echo " DATA_DIR: $DATA_DIR ($SRC_DATA)"
echo " Tailscale IPv4: ${TS_IP:-n/a}"
echo " Log: $LOG_PATH"
echo "==============================================="

mkdir -p logs "$DATA_DIR"
# SIN --reload a proposito: un solo proceso python = Ctrl+C o cierre de terminal
# siempre libera el puerto (con --reload el hijo watcher quedaba huerfano).
.venv/bin/python -m uvicorn node.app.main:app --host 0.0.0.0 --port "$NODE_PORT" >>"$LOG_PATH" 2>&1 &
NODE_PID=$!
# EXIT cubre salida normal; HUP/INT/TERM cubren cierre de terminal y Ctrl+C.
trap 'kill $NODE_PID 2>/dev/null; echo "stopped node $NODE_ID (PID $NODE_PID)."' EXIT HUP INT TERM

if [ -n "${TS_IP:-}" ]; then BASE_URL="http://$TS_IP:$NODE_PORT"; else BASE_URL="http://127.0.0.1:$NODE_PORT"; fi

register_once() {
  HEALTH="$(curl -fs --max-time 3 "$LOCAL_BASE/internal/health" 2>/dev/null || true)"
  BODY="$(NODE_ID="$NODE_ID" BASE_URL="$BASE_URL" HEALTH="$HEALTH" .venv/bin/python -c '
import json, os
h = {}
try: h = json.loads(os.environ.get("HEALTH") or "{}")
except Exception: h = {}
if not isinstance(h, dict): h = {}
payload = {"node_id": os.environ["NODE_ID"], "base_url": os.environ["BASE_URL"]}
for k in ("disk_free", "files_stored", "uptime_secs", "version"):
    if k in h: payload[k] = h[k]
print(json.dumps(payload))
' 2>/dev/null)"
  CODE="$(curl -s --max-time 5 -o /dev/null -w '%{http_code}' -X POST "$COORDINATOR_URL/nodes/register" -H "Content-Type: application/json" -d "$BODY" 2>/dev/null || echo 000)"
  if [ "$CODE" = "200" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') registered node=$NODE_ID base=$BASE_URL coord=$COORDINATOR_URL"
    return 0
  else
    echo "$(date '+%Y-%m-%d %H:%M:%S') register pending node=$NODE_ID coord=$COORDINATOR_URL http=$CODE (will retry on next beat)"
    return 1
  fi
}

READY=""
for _ in $(seq 1 20); do
  sleep 1
  if ! kill -0 "$NODE_PID" 2>/dev/null; then break; fi
  if curl -fs "$LOCAL_BASE/internal/health" >/dev/null 2>&1; then READY=1; break; fi
done
if [ -z "${READY:-}" ]; then echo "NODE FAIL: never became ready. Tail of $LOG_PATH:"; tail -20 "$LOG_PATH"; exit 1; fi

register_once || true

echo "node up, heartbeating: node=$NODE_ID local=$LOCAL_BASE base=$BASE_URL coord=$COORDINATOR_URL every=${INTERVAL_SECS}s (Ctrl+C stops node + loop)"
while true; do
  STAMP="$(date '+%Y-%m-%d %H:%M:%S')"
  if ! HEALTH="$(curl -fs --max-time 5 "$LOCAL_BASE/internal/health" 2>/dev/null)"; then
    echo "$STAMP beat transient-error node=$NODE_ID local health unreachable"
    sleep "$INTERVAL_SECS"; continue
  fi
  BODY="$(NODE_ID="$NODE_ID" HEALTH="$HEALTH" .venv/bin/python -c '
import json, os, sys
h = json.loads(os.environ.get("HEALTH") or "{}")
print(json.dumps({"node_id": os.environ["NODE_ID"], **{k: h.get(k) for k in ("disk_free", "files_stored", "uptime_secs", "version")}}))
' 2>/dev/null)"
  CODE="$(curl -s --max-time 5 -o /dev/null -w '%{http_code}' -X POST "$COORDINATOR_URL/nodes/heartbeat" -H "Content-Type: application/json" -d "$BODY" 2>/dev/null || echo 000)"
  if [ "$CODE" = "200" ]; then
    echo "$STAMP beat ok node=$NODE_ID"
  elif [ "$CODE" = "404" ]; then
    echo "$STAMP beat node=$NODE_ID rejected (404) -> re-registering"
    register_once || true
  else
    echo "$STAMP beat dead-coordinator node=$NODE_ID coord=$COORDINATOR_URL http=$CODE"
  fi
  sleep "$INTERVAL_SECS"
done

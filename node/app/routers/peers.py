"""Node-to-node mesh awareness via the coordinator registry + direct probes (requires X-Internal-Key).

Discovery via GET /nodes, sequential probes to GET /internal/health with
timeout + controlled retries (timeout/connection errors only). In-memory
state per sibling tracks consecutive failures:

- available (0 failures) / degraded (1) / disconnected (>=2).

TTL cache avoids probe storms on periodic polling; ?refresh=true forces
a fresh round. Inbound requires X-Internal-Key, outbound reuses it.
Details are sanitized (truncated, never include secrets).
"""
import os
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends

from common.security import require_internal_key

router = APIRouter(tags=["peers"])

_PEER_STATE: dict[str, dict] = {}
_PEERS_CACHE: dict = {"timestamp": None, "coord": None,
                      "self_id": None, "row_ids": None, "peers": None}


def _self_id() -> str:
    return os.getenv("NODE_ID", "node-1")


def _coord_url() -> str:
    return os.getenv("COORDINATOR_URL", "http://127.0.0.1:8000")


def _internal_headers() -> dict:
    return {"X-Internal-Key": os.getenv("X_INTERNAL_KEY", "")}


def _peers_ttl() -> int:
    try:
        return max(0, int(os.getenv("PEERS_TTL",
                                   os.getenv("HEARTBEAT_INTERVAL", "10"))))
    except (TypeError, ValueError):
        return 10


def _peers_timeout() -> int:
    try:
        return min(10, max(1, int(os.getenv("PEERS_TIMEOUT", "3"))))
    except (TypeError, ValueError):
        return 3


def _peers_retries() -> int:
    try:
        return min(2, max(0, int(os.getenv("PEERS_RETRIES", "1"))))
    except (TypeError, ValueError):
        return 1


def _classify(failures: int) -> str:
    if failures <= 0:
        return "available"
    if failures == 1:
        return "degraded"
    return "disconnected"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize(detail: object) -> str:
    return str(detail)[:200]


@router.get("/peers", dependencies=[Depends(require_internal_key)])
def list_peers(refresh: bool = False):
    self_id = _self_id()
    coord = _coord_url()
    headers = _internal_headers()
    timeout = _peers_timeout()
    ttl = _peers_ttl()
    max_retries = _peers_retries()
    try:
        resp = httpx.get(f"{coord}/nodes", headers=headers, timeout=5)
        if resp.status_code != 200:
            raise RuntimeError(f"coordinator status {resp.status_code}")
        payload = resp.json()
        if not isinstance(payload, dict):
            raise RuntimeError("coordinator returned non-object payload")
        rows = payload.get("live", []) + payload.get("dead", [])
    except Exception as exc:
        return {
            "node_id": self_id,
            "coordinator": {"url": coord, "reachable": False,
                            "error": _sanitize(exc)},
            "peers": [],
            "warning": f"coordinator unreachable at {coord}",
            "cached": False,
        }
    siblings: list[tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        nid = row.get("node_id")
        base = row.get("base_url")
        if nid == self_id or not nid or not base:
            continue
        siblings.append((nid, base))
    row_ids = tuple(sorted(n for n, _ in siblings))
    now = time.time()
    cached = _PEERS_CACHE
    if (not refresh and cached["timestamp"] is not None
            and cached["peers"] is not None
            and cached["coord"] == coord
            and cached["self_id"] == self_id
            and cached["row_ids"] == row_ids
            and (now - cached["timestamp"]) < ttl):
        return {
            "node_id": self_id,
            "coordinator": {"url": coord, "reachable": True},
            "peers": [dict(p) for p in cached["peers"]],
            "cached": True,
        }
    peers: list[dict] = []
    for nid, base in siblings:
        prev = _PEER_STATE.get(nid, {"failures": 0, "last_ok": None})
        failures = 0
        last_ok = prev.get("last_ok")
        detail = "ok"
        reachable = False
        info: dict = {}
        ok = False
        attempts = 1 + max_retries
        last_exc: Exception | None = None
        for _ in range(attempts):
            try:
                probe = httpx.get(f"{base}/internal/health",
                                  headers=headers, timeout=timeout)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                continue
            except Exception as exc:
                last_exc = exc
                break
            if probe.status_code != 200:
                last_exc = None
                detail = f"http {probe.status_code}"
                ok = False
                break
            try:
                info = probe.json()
            except Exception:
                info = {}
            if not isinstance(info, dict):
                info = {}
            peer_id = info.get("node_id")
            if peer_id is not None and peer_id != nid:
                detail = "node_id mismatch"
                ok = False
                break
            detail = _sanitize(info.get("version",
                                        info.get("status", "ok")))
            ok = True
            last_exc = None
            break
        if ok:
            failures = 0
            last_ok = _now_iso()
            status = "available"
            reachable = True
        else:
            if last_exc is not None:
                if isinstance(last_exc, httpx.TimeoutException):
                    detail = "timeout"
                else:
                    detail = _sanitize(last_exc)
            failures = int(prev.get("failures", 0)) + 1
            status = _classify(failures)
            reachable = False
        _PEER_STATE[nid] = {"failures": failures, "last_ok": last_ok,
                            "base_url": base}
        peers.append({"node_id": nid, "base_url": base,
                      "reachable": reachable, "detail": detail,
                      "status": status, "failures": failures,
                      "last_seen": last_ok})
    _PEERS_CACHE.update({"timestamp": time.time(), "coord": coord,
                         "self_id": self_id, "row_ids": row_ids,
                         "peers": [dict(p) for p in peers]})
    return {
        "node_id": self_id,
        "coordinator": {"url": coord, "reachable": True},
        "peers": peers,
        "cached": False,
    }

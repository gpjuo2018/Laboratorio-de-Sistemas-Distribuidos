"""Coordinator node-facing surface (internal, requires X-Internal-Key).

Endpoints: register + heartbeat + live/dead listing + manual repair check.
There is NO background loop; repair runs only on POST /nodes/check.
"""
from datetime import datetime, timezone
import logging
import threading

from fastapi import APIRouter, Depends, HTTPException, Request

from common.config import APP_VERSION
from common.hashing import rendezvous_rank
from common.security import get_internal_key, require_internal_key
from coordinator.app.persistence.models import (
    heartbeat_node,
    last_event,
    list_events,
    list_nodes,
    list_objects,
    log_event,
    register_node,
    upsert_object,
)
from coordinator.app.services.nodes import get_dead_nodes, get_nodes, is_live
from coordinator.app.services.placement import RF
from coordinator.app.services.replication import fetch_verified, replicate

router = APIRouter(prefix="/nodes", tags=["nodes"])

_log = logging.getLogger(__name__)
_CHECK_LOCK = threading.Lock()


def _require_non_empty(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=422, detail=f"invalid {field}")
    return value.strip()


async def _parse_json_body(request: Request) -> dict:
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="invalid body")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid body")
    return payload


def _enriched_fields(payload: dict) -> dict:
    return {
        "disk_free": payload.get("disk_free"),
        "files_stored": payload.get("files_stored"),
        "uptime_secs": payload.get("uptime_secs"),
        "version": payload.get("version"),
    }


def _live_dead_rows(rows: list, now: datetime) -> tuple[list, list]:
    live = [r for r in rows if is_live(r.get("last_seen", ""), now)]
    dead = [r for r in rows if not is_live(r.get("last_seen", ""), now)]
    return live, dead


@router.post("/register", dependencies=[Depends(require_internal_key)])
async def register(request: Request):
    payload = await _parse_json_body(request)
    node_id = _require_non_empty(payload.get("node_id"), "node_id")
    base_url = _require_non_empty(payload.get("base_url"), "base_url")
    fields = _enriched_fields(payload)
    _from = request.client.host if request.client else "?"
    _log.info("[nodes] register node=%s base=%s from=%s",
              node_id, base_url, _from)
    return register_node(node_id, base_url, **fields)


@router.post("/heartbeat", dependencies=[Depends(require_internal_key)])
async def heartbeat(request: Request):
    payload = await _parse_json_body(request)
    node_id = _require_non_empty(payload.get("node_id"), "node_id")
    fields = _enriched_fields(payload)
    _from = request.client.host if request.client else "?"
    prev_seen = ""
    for _row in list_nodes():
        if _row.get("node_id") == node_id:
            prev_seen = _row.get("last_seen", "")
            break
    row = heartbeat_node(node_id, **fields)
    if row is None:
        _log.info("[nodes] heartbeat node=%s from=%s -> 404 "
                  "(unknown node, register first)", node_id, _from)
        raise HTTPException(status_code=404,
                            detail="unknown node, register first")
    _log.info("[nodes] heartbeat node=%s from=%s -> 200", node_id, _from)
    now = datetime.now(timezone.utc)
    if (prev_seen and not is_live(prev_seen, now)
            and is_live(row.get("last_seen", ""), now)):
        log_event("node_up", node_id,
                  f"node {node_id} revived (was stale since {prev_seen})")
    return row


@router.get("", dependencies=[Depends(require_internal_key)])
@router.get("/", dependencies=[Depends(require_internal_key)])
async def list_membership():
    rows = list_nodes()
    now = datetime.now(timezone.utc)
    live, dead = _live_dead_rows(rows, now)
    return {"live": live, "dead": dead}


@router.get("/events", dependencies=[Depends(require_internal_key)])
async def read_events(limit: int = 50):
    try:
        lim = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        lim = 50
    return list_events(limit=lim)


@router.get("/map", dependencies=[Depends(require_internal_key)])
async def network_map():
    rows = list_nodes()
    now = datetime.now(timezone.utc)
    live, dead = _live_dead_rows(rows, now)
    objects = list_objects()
    files = [{"name": m["name"], "replicas": list(m.get("replicas", []))}
             for m in objects]
    return {
        "coordinator": {
            "version": APP_VERSION,
            "time_utc": now.isoformat(),
            "objects": len(objects),
            "nodes_registered": len(rows),
        },
        "live": live,
        "dead": dead,
        "files": files,
        "recent_events": list_events(limit=10),
    }


@router.post("/check", dependencies=[Depends(require_internal_key)])
def check_and_repair():
    with _CHECK_LOCK:
        return _run_check_and_repair()


def _run_check_and_repair():
    # Liveness via the single shared helper (no inline datetime arithmetic).
    rows = list_nodes()
    now = datetime.now(timezone.utc)
    if rows:
        live_nodes = [r["base_url"] for r in rows
                      if is_live(r.get("last_seen", ""), now)]
        dead_ids = [r["node_id"] for r in rows
                    if not is_live(r.get("last_seen", ""), now)]
    else:
        live_nodes = get_nodes()
        dead_ids = [d.get("node_id") for d in get_dead_nodes()
                    if d.get("node_id")]
    live_set = set(live_nodes)
    internal_key = get_internal_key()
    objects = list_objects()
    # Transition-only death reporting: log node_down once per fresh death.
    for _row in rows:
        _nid = _row.get("node_id")
        if _nid and not is_live(_row.get("last_seen", ""), now):
            _last = last_event(_nid)
            if _last is None or _last.get("type") != "node_down":
                log_event("node_down", _nid,
                          f"node {_nid} dead"
                          f" (last_seen {_row.get('last_seen', '')})")
    repaired: list[str] = []
    failed: list = []
    for meta in objects:
        name = meta["name"]
        digest = meta["sha256"]
        size = meta["size"]
        replicas = list(meta.get("replicas", []))
        live = [r for r in replicas if r in live_set]
        missing = RF - len(live)
        if missing <= 0:
            continue
        body = fetch_verified(name, digest, live, internal_key)
        if body is None:
            failed.append(name)
            continue
        cands = [n for n in rendezvous_rank(name, live_nodes)
                 if n not in live][:missing]
        if not cands:
            failed.append(name)
            continue
        res = replicate(name, body, digest, cands, internal_key)
        if res and all(r.get("ok") for r in res):
            upsert_object(name, digest, size, live + cands)
            repaired.append(name)
        else:
            failed.append(name)
    if repaired or failed:
        log_event("repair", None,
                  {"repaired": repaired, "failed": failed})
    return {"checked": len(objects), "repaired": repaired,
            "failed": failed, "dead": dead_ids}

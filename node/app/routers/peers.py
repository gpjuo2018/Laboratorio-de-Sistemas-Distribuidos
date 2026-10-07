"""Node-to-node mesh awareness via the coordinator registry + direct probes."""
import os

import httpx
from fastapi import APIRouter

router = APIRouter(tags=["peers"])


def _self_id() -> str:
    return os.getenv("NODE_ID", "node-1")


def _coord_url() -> str:
    return os.getenv("COORDINATOR_URL", "http://127.0.0.1:8000")


@router.get("/peers")
def list_peers():
    self_id = _self_id()
    coord = _coord_url()
    try:
        resp = httpx.get(f"{coord}/nodes", timeout=5)
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
                            "error": str(exc)[:200]},
            "peers": [],
            "warning": f"coordinator unreachable at {coord}",
        }
    peers: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        nid = row.get("node_id")
        base = row.get("base_url")
        if nid == self_id or not nid or not base:
            continue
        try:
            probe = httpx.get(f"{base}/internal/health", timeout=3)
            if probe.status_code == 200:
                try:
                    info = probe.json()
                except Exception:
                    info = {}
                if not isinstance(info, dict):
                    info = {}
                detail = str(info.get("version",
                                      info.get("status", "ok")))
                peers.append({"node_id": nid, "base_url": base,
                              "reachable": True, "detail": detail})
            else:
                peers.append({"node_id": nid, "base_url": base,
                              "reachable": False,
                              "detail": f"http {probe.status_code}"})
        except Exception as exc:
            peers.append({"node_id": nid, "base_url": base,
                          "reachable": False, "detail": str(exc)[:200]})
    return {
        "node_id": self_id,
        "coordinator": {"url": coord, "reachable": True},
        "peers": peers,
    }

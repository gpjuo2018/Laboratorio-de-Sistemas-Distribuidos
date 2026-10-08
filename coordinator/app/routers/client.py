"""Coordinator client-facing routes: write-2 / read-1 fan-out over nodes."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from common import http_client
from common.hashing import sha256_bytes
from common.security import get_internal_key, require_api_key
from coordinator.app.persistence.models import (
    delete_object,
    get_object,
    list_objects,
    upsert_object,
)
from coordinator.app.services.nodes import get_nodes
from coordinator.app.services.placement import RF, rendezvous_pick
from coordinator.app.services.replication import fetch_verified, replicate

router = APIRouter(prefix="/files", tags=["client"])


def _guard(name: str) -> None:
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="invalid name")


@router.put("/{name}", dependencies=[Depends(require_api_key)])
async def upload_file(name: str, request: Request):
    _guard(name)
    body = await request.body()
    digest = sha256_bytes(body)
    nodes = get_nodes()
    if len(nodes) < 1:
        raise HTTPException(status_code=503, detail="no nodes available")
    targets = rendezvous_pick(name, nodes)[:RF]
    res = replicate(name, body, digest, targets, get_internal_key())
    if res and all(r["ok"] for r in res):
        upsert_object(name, digest, len(body), targets)
        return {"name": name, "sha256": digest, "size": len(body),
                "replicas": targets}
    return JSONResponse(status_code=502,
                        content={"detail": "replication failed", "targets": res})


@router.get("/{name}", dependencies=[Depends(require_api_key)])
def download_file(name: str):
    _guard(name)
    meta = get_object(name)
    if meta is None:
        raise HTTPException(status_code=404, detail="not found")
    body = fetch_verified(name, meta["sha256"], meta["replicas"],
                          get_internal_key())
    if body is None:
        raise HTTPException(status_code=502,
                            detail="all replicas corrupt or unavailable")
    return Response(content=body, media_type="application/octet-stream")


@router.get("", dependencies=[Depends(require_api_key)])
def list_files():
    return [
        {"name": o["name"], "sha256": o["sha256"], "size": o["size"],
         "replicas": o["replicas"]}
        for o in list_objects()
    ]


@router.delete("/{name}", dependencies=[Depends(require_api_key)])
def delete_file(name: str):
    _guard(name)
    meta = get_object(name)
    if meta is None:
        raise HTTPException(status_code=404, detail="not found")
    results = []
    internal_headers = {"X-Internal-Key": get_internal_key()}
    for t in meta["replicas"]:
        entry = {"target": t, "ok": False, "status": None, "error": None}
        try:
            resp = http_client.forward_delete(f"{t}/store/{name}",
                                              headers=internal_headers)
            entry["status"] = resp.status_code
            if resp.status_code in (200, 204, 404):
                entry["ok"] = True
            else:
                entry["error"] = f"http {resp.status_code}"
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
        results.append(entry)
    delete_object(name)
    return {"name": name, "deleted": True, "replicas": results}

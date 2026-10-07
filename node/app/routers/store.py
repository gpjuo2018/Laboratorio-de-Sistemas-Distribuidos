"""Node block-store with SHA-256 integrity verification."""
import os
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse

from common.config import APP_VERSION
from common.hashing import sha256_bytes, sha256_stream

router = APIRouter(tags=["store"])
NOT_IMPL = {"detail": "not implemented (skeleton)"}

_BOOT_TIME = time.time()


def _guard(name: str) -> None:
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="invalid name")


def _data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "./data"))


@router.put("/store/{name}")
async def store_put(name: str, request: Request,
                    x_expected_sha256: str | None = Header(default=None)):
    _guard(name)
    body = await request.body()
    digest = sha256_bytes(body)
    if x_expected_sha256 is not None and x_expected_sha256 != digest:
        raise HTTPException(status_code=422, detail="sha256 mismatch")
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / name).write_bytes(body)
    return {"name": name, "sha256": digest, "size": len(body)}


@router.get("/store/{name}")
def store_get(name: str):
    _guard(name)
    path = _data_dir() / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    digest = sha256_stream(str(path))
    return FileResponse(str(path), headers={"X-SHA256": digest})


@router.delete("/store/{name}")
def store_delete(name: str):
    _guard(name)
    path = _data_dir() / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    path.unlink()
    return {"name": name, "deleted": True}


@router.get("/internal/health")
def internal_health():
    data_dir = _data_dir()
    if data_dir.is_dir():
        files_stored = sum(1 for p in data_dir.iterdir() if p.is_file())
    else:
        files_stored = 0
    try:
        disk_free = shutil.disk_usage(str(data_dir)).free
    except (FileNotFoundError, NotADirectoryError, OSError):
        disk_free = shutil.disk_usage(".").free
    return {
        "status": "ok",
        "node_id": os.getenv("NODE_ID", "node-1"),
        "version": APP_VERSION,
        "uptime_secs": time.time() - _BOOT_TIME,
        "files_stored": files_stored,
        "disk_free": disk_free,
        "data_dir": str(data_dir),
    }

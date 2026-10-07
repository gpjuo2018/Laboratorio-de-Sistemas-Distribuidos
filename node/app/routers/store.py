"""Node block-store with SHA-256 integrity verification."""
import os
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse

from common.hashing import sha256_bytes, sha256_stream

router = APIRouter(tags=["store"])
NOT_IMPL = {"detail": "not implemented (skeleton)"}


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


@router.get("/internal/health", status_code=501)
def internal_health():
    return NOT_IMPL

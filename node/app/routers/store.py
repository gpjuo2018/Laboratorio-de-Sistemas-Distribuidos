"""Node block-store stubs (skeleton, no logic)."""
from fastapi import APIRouter

router = APIRouter(tags=["store"])
NOT_IMPL = {"detail": "not implemented (skeleton)"}


@router.put("/store/{name}", status_code=501)
def store_put(name: str):
    return NOT_IMPL


@router.get("/store/{name}", status_code=501)
def store_get(name: str):
    return NOT_IMPL


@router.delete("/store/{name}", status_code=501)
def store_delete(name: str):
    return NOT_IMPL


@router.get("/internal/health", status_code=501)
def internal_health():
    return NOT_IMPL

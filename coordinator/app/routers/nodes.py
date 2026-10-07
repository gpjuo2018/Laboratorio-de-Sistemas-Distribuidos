"""Coordinator node-facing stubs (skeleton, no logic)."""
from fastapi import APIRouter

router = APIRouter(prefix="/nodes", tags=["nodes"])
NOT_IMPL = {"detail": "not implemented (skeleton)"}


@router.post("/register", status_code=501)
def register_node():
    return NOT_IMPL


@router.post("/heartbeat", status_code=501)
def node_heartbeat():
    return NOT_IMPL

"""Coordinator client-facing stubs (skeleton, no logic)."""
from fastapi import APIRouter, Depends, Header, HTTPException

from common.security import API_KEY_HEADER

router = APIRouter(prefix="/files", tags=["client"])
NOT_IMPL = {"detail": "not implemented (skeleton)"}


def require_api_key(x_api_key: str | None = Header(default=None)):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing api key")
    return x_api_key


@router.put("/{name}", status_code=501, dependencies=[Depends(require_api_key)])
def upload_file(name: str):
    return NOT_IMPL


@router.get("/{name}", status_code=501, dependencies=[Depends(require_api_key)])
def download_file(name: str):
    return NOT_IMPL


@router.get("", status_code=501, dependencies=[Depends(require_api_key)])
def list_files():
    return NOT_IMPL


@router.delete("/{name}", status_code=501, dependencies=[Depends(require_api_key)])
def delete_file(name: str):
    return NOT_IMPL

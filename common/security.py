"""Auth header constants + key verifiers.

X_API_KEY: public edge (client -> coordinator /files*).
X_INTERNAL_KEY: internal plane (coordinator <-> nodes).
Env is read on each call so tests can monkeypatch.
Never log or return secret values; callers use generic details.
"""
import hmac
import os

from fastapi import Header, HTTPException

INTERNAL_KEY_HEADER = "X-Internal-Key"
API_KEY_HEADER = "X-API-Key"


def _expected(name: str) -> str:
    return os.getenv(name, "")


def verify_api_key(provided: str | None) -> bool:
    """True only if provided equals X_API_KEY env (constant-time)."""
    expected = _expected("X_API_KEY")
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided, expected)


def verify_internal_key(provided: str | None) -> bool:
    """True only if provided equals X_INTERNAL_KEY env (constant-time)."""
    expected = _expected("X_INTERNAL_KEY")
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided, expected)


def get_internal_key() -> str:
    return _expected("X_INTERNAL_KEY")


def get_api_key() -> str:
    return _expected("X_API_KEY")


def require_api_key(x_api_key: str | None = Header(default=None)) -> str:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing api key")
    if not verify_api_key(x_api_key):
        raise HTTPException(status_code=403, detail="invalid api key")
    return x_api_key


def require_internal_key(x_internal_key: str | None = Header(default=None)) -> str:
    if not x_internal_key:
        raise HTTPException(status_code=401, detail="missing internal key")
    if not verify_internal_key(x_internal_key):
        raise HTTPException(status_code=403, detail="invalid internal key")
    return x_internal_key

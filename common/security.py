"""Auth header constants + stub verifiers (skeleton only)."""
import os

INTERNAL_KEY_HEADER = "X-Internal-Key"
API_KEY_HEADER = "X-API-Key"


def verify_api_key(provided: str | None) -> bool:
    """Stub: compare against X_API_KEY env (skeleton)."""
    raise NotImplementedError("not implemented (skeleton)")


def verify_internal_key(provided: str | None) -> bool:
    """Stub: compare against X_INTERNAL_KEY env (skeleton)."""
    raise NotImplementedError("not implemented (skeleton)")

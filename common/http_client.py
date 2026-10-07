"""Outbound HTTP stub (coordinator -> nodes)."""
import httpx

REQUEST_TIMEOUT = 5


def forward_put(url: str, data: bytes, headers: dict | None = None):
    """Forward a PUT to a storage node (stub)."""
    raise NotImplementedError("not implemented (skeleton)")

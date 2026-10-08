"""Outbound HTTP (coordinator -> nodes). Sync, no retries (wave 4 owns repair)."""
import httpx

REQUEST_TIMEOUT = 5


def forward_put(url: str, data: bytes, headers: dict | None = None):
    """PUT bytes to a storage node. Returns the httpx.Response."""
    return httpx.put(url, content=data, headers=headers, timeout=REQUEST_TIMEOUT)


def forward_get(url: str, headers: dict | None = None):
    """GET bytes from a storage node. Returns the httpx.Response."""
    return httpx.get(url, headers=headers, timeout=REQUEST_TIMEOUT)


def forward_delete(url: str, headers: dict | None = None):
    """DELETE an object on a storage node. Returns the httpx.Response."""
    return httpx.delete(url, headers=headers, timeout=REQUEST_TIMEOUT)

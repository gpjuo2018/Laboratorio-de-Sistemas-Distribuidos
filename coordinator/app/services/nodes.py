"""Node list seam with live heartbeat registry + static env fallback."""
import os
from datetime import datetime, timezone

from common.config import DEAD_TIMEOUT

DEFAULT_NODES = (
    "http://127.0.0.1:8001,http://127.0.0.1:8002,"
    "http://127.0.0.1:8003,http://127.0.0.1:8004"
)


def _static_nodes() -> list[str]:
    raw = os.getenv("NODES", DEFAULT_NODES)
    return [n.strip() for n in raw.split(",") if n.strip()]


def _parse_iso(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def is_live(last_seen_iso: str, now: datetime | None = None,
            timeout: int = DEAD_TIMEOUT) -> bool:
    """True when (now - last_seen) <= timeout seconds; False on bad input."""
    seen = _parse_iso(last_seen_iso) if isinstance(last_seen_iso, str) else None
    if seen is None:
        return False
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    try:
        return (now - seen).total_seconds() <= timeout
    except Exception:
        return False


def get_nodes() -> list[str]:
    """Return base_urls of LIVE registered nodes; static env if registry empty.

    Falls back to the static NODES env list when the registry has no rows
    or on ANY registry/SQLite error (coordinator must boot with corrupt DB).
    """
    try:
        from coordinator.app.persistence.models import list_nodes as _list
        rows = _list()
    except Exception:
        return _static_nodes()
    if not rows:
        return _static_nodes()
    now = datetime.now(timezone.utc)
    live = [r["base_url"] for r in rows
            if is_live(r.get("last_seen", ""), now)]
    return live


def get_dead_nodes() -> list[dict]:
    """Return registered-but-stale node rows; [] on ANY registry error."""
    try:
        from coordinator.app.persistence.models import list_nodes as _list
        rows = _list()
    except Exception:
        return []
    now = datetime.now(timezone.utc)
    return [r for r in rows if not is_live(r.get("last_seen", ""), now)]

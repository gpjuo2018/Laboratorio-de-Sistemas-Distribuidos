"""SQLite metadata store (stdlib sqlite3 only, no ORM)."""
import json
import os
import sqlite3
from datetime import datetime, timezone


def _db_path() -> str:
    return os.getenv("METADATA_DB_PATH", "./metadata.db")


def init_db() -> None:
    """Create the objects + nodes tables if missing (idempotent)."""
    con = sqlite3.connect(_db_path(), timeout=5.0)
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS objects ("
            " name TEXT PRIMARY KEY,"
            " sha256 TEXT NOT NULL,"
            " size INTEGER NOT NULL,"
            " replicas_json TEXT NOT NULL,"
            " updated_at TEXT NOT NULL"
            ")"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS nodes ("
            " node_id TEXT PRIMARY KEY,"
            " base_url TEXT NOT NULL,"
            " last_seen TEXT NOT NULL,"
            " disk_free INTEGER,"
            " files_stored INTEGER,"
            " uptime_secs REAL,"
            " version TEXT"
            ")"
        )
        # Migration-safe upgrade: existing production DBs keep their rows;
        # ADD COLUMN is a no-op when the column already exists.
        for _coldef in ("files_stored INTEGER", "uptime_secs REAL",
                        "version TEXT"):
            try:
                con.execute(f"ALTER TABLE nodes ADD COLUMN {_coldef}")
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
        con.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " ts TEXT NOT NULL,"
            " type TEXT NOT NULL,"
            " node_id TEXT,"
            " detail TEXT"
            ")"
        )
        con.commit()
    finally:
        con.close()


def _row_to_obj(row) -> dict:
    name, sha256, size, replicas_json, _updated = row
    return {
        "name": name,
        "sha256": sha256,
        "size": size,
        "replicas": json.loads(replicas_json),
    }


def upsert_object(name: str, sha256: str, size: int, replicas: list) -> None:
    """Insert or replace a metadata row (overwrite allowed)."""
    init_db()
    updated_at = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(_db_path(), timeout=5.0)
    try:
        con.execute(
            "INSERT INTO objects (name, sha256, size, replicas_json, updated_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(name) DO UPDATE SET"
            " sha256=excluded.sha256, size=excluded.size,"
            " replicas_json=excluded.replicas_json, updated_at=excluded.updated_at",
            (name, sha256, size, json.dumps(list(replicas)), updated_at),
        )
        con.commit()
    finally:
        con.close()


def get_object(name: str) -> dict | None:
    """Return metadata dict for name, or None if unknown."""
    init_db()
    con = sqlite3.connect(_db_path(), timeout=5.0)
    try:
        row = con.execute(
            "SELECT name, sha256, size, replicas_json, updated_at"
            " FROM objects WHERE name = ?",
            (name,),
        ).fetchone()
    finally:
        con.close()
    return _row_to_obj(row) if row is not None else None


def list_objects() -> list[dict]:
    """Return all metadata rows as dicts."""
    init_db()
    con = sqlite3.connect(_db_path(), timeout=5.0)
    try:
        rows = con.execute(
            "SELECT name, sha256, size, replicas_json, updated_at"
            " FROM objects ORDER BY name"
        ).fetchall()
    finally:
        con.close()
    return [_row_to_obj(r) for r in rows]


def delete_object(name: str) -> None:
    """Remove a metadata row (no-op if unknown)."""
    init_db()
    con = sqlite3.connect(_db_path(), timeout=5.0)
    try:
        con.execute("DELETE FROM objects WHERE name = ?", (name,))
        con.commit()
    finally:
        con.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_node(row) -> dict:
    vals = list(row) + [None] * (7 - len(row))
    node_id, base_url, last_seen, disk_free = vals[0], vals[1], vals[2], vals[3]
    files_stored, uptime_secs, version = vals[4], vals[5], vals[6]
    return {
        "node_id": node_id,
        "base_url": base_url,
        "last_seen": last_seen,
        "disk_free": disk_free,
        "files_stored": files_stored,
        "uptime_secs": uptime_secs,
        "version": version,
    }


def register_node(node_id: str, base_url: str, disk_free=None,
                   files_stored=None, uptime_secs=None, version=None,
                   now_iso: str | None = None) -> dict:
    """Upsert a node row (insert or replace last_seen/base_url), return row."""
    init_db()
    now = now_iso if now_iso is not None else _now_iso()
    con = sqlite3.connect(_db_path(), timeout=5.0)
    try:
        con.execute(
            "INSERT INTO nodes (node_id, base_url, last_seen, disk_free,"
            " files_stored, uptime_secs, version)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(node_id) DO UPDATE SET"
            " base_url=excluded.base_url,"
            " last_seen=excluded.last_seen,"
            " disk_free=excluded.disk_free,"
            " files_stored=excluded.files_stored,"
            " uptime_secs=excluded.uptime_secs,"
            " version=excluded.version",
            (node_id, base_url, now, disk_free, files_stored,
             uptime_secs, version),
        )
        con.commit()
        row = con.execute(
            "SELECT node_id, base_url, last_seen, disk_free,"
            " files_stored, uptime_secs, version"
            " FROM nodes WHERE node_id = ?",
            (node_id,),
        ).fetchone()
    finally:
        con.close()
    return _row_to_node(row)


def heartbeat_node(node_id: str, disk_free=None, files_stored=None,
                    uptime_secs=None, version=None,
                    now_iso: str | None = None) -> dict | None:
    """Update last_seen of a KNOWN node; return None if unknown."""
    init_db()
    now = now_iso if now_iso is not None else _now_iso()
    con = sqlite3.connect(_db_path(), timeout=5.0)
    try:
        row = con.execute(
            "SELECT node_id, base_url, last_seen, disk_free,"
            " files_stored, uptime_secs, version"
            " FROM nodes WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        if row is None:
            return None
        fields: dict = {"last_seen": now}
        if disk_free is not None:
            fields["disk_free"] = disk_free
        if files_stored is not None:
            fields["files_stored"] = files_stored
        if uptime_secs is not None:
            fields["uptime_secs"] = uptime_secs
        if version is not None:
            fields["version"] = version
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        con.execute(
            f"UPDATE nodes SET {set_clause} WHERE node_id = ?",
            (*fields.values(), node_id),
        )
        con.commit()
        row = con.execute(
            "SELECT node_id, base_url, last_seen, disk_free,"
            " files_stored, uptime_secs, version"
            " FROM nodes WHERE node_id = ?",
            (node_id,),
        ).fetchone()
    finally:
        con.close()
    return _row_to_node(row) if row is not None else None


def list_nodes() -> list[dict]:
    """Return all registered node rows as dicts."""
    init_db()
    con = sqlite3.connect(_db_path(), timeout=5.0)
    try:
        rows = con.execute(
            "SELECT node_id, base_url, last_seen, disk_free,"
            " files_stored, uptime_secs, version"
            " FROM nodes ORDER BY node_id"
        ).fetchall()
    finally:
        con.close()
    return [_row_to_node(r) for r in rows]


def set_last_seen(node_id: str, iso: str) -> None:
    """Test seam: force last_seen of a node (no-op if unknown)."""
    init_db()
    con = sqlite3.connect(_db_path(), timeout=5.0)
    try:
        con.execute(
            "UPDATE nodes SET last_seen = ? WHERE node_id = ?",
            (iso, node_id),
        )
        con.commit()
    finally:
        con.close()


def _row_to_event(row) -> dict:
    eid, ts, type_, node_id, detail = row
    return {
        "id": eid,
        "ts": ts,
        "type": type_,
        "node_id": node_id,
        "detail": detail,
    }


def log_event(type: str, node_id: str | None, detail=None,
              ts: str | None = None) -> dict:
    """Append one event row (node_up / node_down / repair) and return it."""
    init_db()
    stamp = ts if ts is not None else _now_iso()
    if isinstance(detail, (dict, list)):
        detail_text = json.dumps(detail)
    elif detail is None:
        detail_text = None
    else:
        detail_text = str(detail)
    con = sqlite3.connect(_db_path(), timeout=5.0)
    try:
        cur = con.execute(
            "INSERT INTO events (ts, type, node_id, detail)"
            " VALUES (?, ?, ?, ?)",
            (stamp, type, node_id, detail_text),
        )
        con.commit()
        row = con.execute(
            "SELECT id, ts, type, node_id, detail FROM events WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    finally:
        con.close()
    return _row_to_event(row)


def list_events(limit: int = 50) -> list[dict]:
    """Return newest-first event rows (ORDER BY id DESC)."""
    init_db()
    try:
        lim = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        lim = 50
    con = sqlite3.connect(_db_path(), timeout=5.0)
    try:
        rows = con.execute(
            "SELECT id, ts, type, node_id, detail FROM events"
            " ORDER BY id DESC LIMIT ?",
            (lim,),
        ).fetchall()
    finally:
        con.close()
    return [_row_to_event(r) for r in rows]


def last_event(node_id: str) -> dict | None:
    """Return the newest event row for a node, or None if it has none."""
    init_db()
    con = sqlite3.connect(_db_path(), timeout=5.0)
    try:
        row = con.execute(
            "SELECT id, ts, type, node_id, detail FROM events"
            " WHERE node_id = ? ORDER BY id DESC LIMIT 1",
            (node_id,),
        ).fetchone()
    finally:
        con.close()
    return _row_to_event(row) if row is not None else None

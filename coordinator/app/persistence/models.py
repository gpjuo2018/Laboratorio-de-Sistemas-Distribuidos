"""SQLite metadata store (stdlib sqlite3 only, no ORM)."""
import json
import os
import sqlite3
from datetime import datetime, timezone


def _db_path() -> str:
    return os.getenv("METADATA_DB_PATH", "./metadata.db")


def init_db() -> None:
    """Create the objects + nodes tables if missing (idempotent)."""
    con = sqlite3.connect(_db_path())
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
            " disk_free INTEGER"
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
    con = sqlite3.connect(_db_path())
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
    con = sqlite3.connect(_db_path())
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
    con = sqlite3.connect(_db_path())
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
    con = sqlite3.connect(_db_path())
    try:
        con.execute("DELETE FROM objects WHERE name = ?", (name,))
        con.commit()
    finally:
        con.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_node(row) -> dict:
    node_id, base_url, last_seen, disk_free = row
    return {
        "node_id": node_id,
        "base_url": base_url,
        "last_seen": last_seen,
        "disk_free": disk_free,
    }


def register_node(node_id: str, base_url: str, disk_free=None,
                  now_iso: str | None = None) -> dict:
    """Upsert a node row (insert or replace last_seen/base_url), return row."""
    init_db()
    now = now_iso if now_iso is not None else _now_iso()
    con = sqlite3.connect(_db_path())
    try:
        con.execute(
            "INSERT INTO nodes (node_id, base_url, last_seen, disk_free)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(node_id) DO UPDATE SET"
            " base_url=excluded.base_url,"
            " last_seen=excluded.last_seen,"
            " disk_free=excluded.disk_free",
            (node_id, base_url, now, disk_free),
        )
        con.commit()
        row = con.execute(
            "SELECT node_id, base_url, last_seen, disk_free"
            " FROM nodes WHERE node_id = ?",
            (node_id,),
        ).fetchone()
    finally:
        con.close()
    return _row_to_node(row)


def heartbeat_node(node_id: str, disk_free=None,
                   now_iso: str | None = None) -> dict | None:
    """Update last_seen of a KNOWN node; return None if unknown."""
    init_db()
    now = now_iso if now_iso is not None else _now_iso()
    con = sqlite3.connect(_db_path())
    try:
        row = con.execute(
            "SELECT node_id, base_url, last_seen, disk_free"
            " FROM nodes WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        if row is None:
            return None
        if disk_free is None:
            con.execute(
                "UPDATE nodes SET last_seen = ? WHERE node_id = ?",
                (now, node_id),
            )
        else:
            con.execute(
                "UPDATE nodes SET last_seen = ?, disk_free = ?"
                " WHERE node_id = ?",
                (now, disk_free, node_id),
            )
        con.commit()
        row = con.execute(
            "SELECT node_id, base_url, last_seen, disk_free"
            " FROM nodes WHERE node_id = ?",
            (node_id,),
        ).fetchone()
    finally:
        con.close()
    return _row_to_node(row) if row is not None else None


def list_nodes() -> list[dict]:
    """Return all registered node rows as dicts."""
    init_db()
    con = sqlite3.connect(_db_path())
    try:
        rows = con.execute(
            "SELECT node_id, base_url, last_seen, disk_free"
            " FROM nodes ORDER BY node_id"
        ).fetchall()
    finally:
        con.close()
    return [_row_to_node(r) for r in rows]


def set_last_seen(node_id: str, iso: str) -> None:
    """Test seam: force last_seen of a node (no-op if unknown)."""
    init_db()
    con = sqlite3.connect(_db_path())
    try:
        con.execute(
            "UPDATE nodes SET last_seen = ? WHERE node_id = ?",
            (iso, node_id),
        )
        con.commit()
    finally:
        con.close()

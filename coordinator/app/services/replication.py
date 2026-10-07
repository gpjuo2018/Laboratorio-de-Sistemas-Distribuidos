"""Fan-out replication: write-2 / read-1 with digest verification."""
from common import http_client
from common.hashing import sha256_bytes


def replicate(name: str, data: bytes, digest: str, targets: list,
              internal_key: str) -> list[dict]:
    """PUT data to every target; ok requires HTTP 200 + matching sha256 echo."""
    results = []
    for t in targets:
        entry = {"target": t, "ok": False, "status": None, "error": None}
        try:
            resp = http_client.forward_put(
                f"{t}/store/{name}",
                data,
                headers={
                    "X-Expected-SHA256": digest,
                    "X-Internal-Key": internal_key,
                },
            )
            entry["status"] = resp.status_code
            if resp.status_code == 200:
                try:
                    echoed = resp.json().get("sha256")
                except Exception as exc:
                    entry["error"] = f"bad json: {exc}"
                    echoed = None
                if echoed == digest:
                    entry["ok"] = True
                elif entry["error"] is None:
                    entry["error"] = f"sha256 echo mismatch: {echoed!r}"
            else:
                entry["error"] = f"http {resp.status_code}"
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
        results.append(entry)
    return results


def fetch_verified(name: str, digest: str, targets: list) -> bytes | None:
    """GET each replica in order; return first body matching digest, else None."""
    for t in targets:
        try:
            resp = http_client.forward_get(f"{t}/store/{name}")
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        body = resp.content
        if sha256_bytes(body) == digest:
            return body
    return None

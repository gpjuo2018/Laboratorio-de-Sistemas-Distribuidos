"""Hashing helpers: rendezvous ranking + streaming SHA-256."""
import hashlib


def rendezvous_rank(key: str, nodes: list) -> list:
    """Rank nodes for key via HRW (desc by sha256("key|node") score)."""
    if not nodes:
        return []
    scored = [
        (int(hashlib.sha256(f"{key}|{node}".encode()).hexdigest(), 16), str(node), node)
        for node in nodes
    ]
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [t[2] for t in scored]


def sha256_bytes(data: bytes) -> str:
    """Return hex SHA-256 digest of in-memory bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_stream(path: str, chunk_size: int = 8 * 1024 * 1024) -> str:
    """Stream file in chunks and return hex digest."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

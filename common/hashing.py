"""Hashing stubs for rendezvous ranking + streaming SHA-256."""


def rendezvous_rank(key: str, nodes: list) -> list:
    """Rank nodes for key (stub).

    Real impl: score = sha256("key|node") per node, sort desc, top-RF.
    """
    raise NotImplementedError("not implemented (skeleton)")


def sha256_stream(path: str, chunk_size: int = 8 * 1024 * 1024) -> str:
    """Stream file in chunks and return hex digest (stub)."""
    raise NotImplementedError("not implemented (skeleton)")

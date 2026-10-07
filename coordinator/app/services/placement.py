"""Placement stub: rendezvous top-RF (skeleton)."""
RF = 2


def rendezvous_pick(key: str, nodes: list) -> list:
    """Pick RF=2 replicas for key (stub).

    Real impl: score = sha256("key|node") per node, take top-2.
    """
    raise NotImplementedError("not implemented (skeleton)")

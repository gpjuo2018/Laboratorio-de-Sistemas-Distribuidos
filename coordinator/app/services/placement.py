"""Placement: rendezvous top-RF replica pick."""
from common.hashing import rendezvous_rank

RF = 2


def rendezvous_pick(key: str, nodes: list, r: int = RF) -> list:
    """Pick top-r replicas for key (HRW order, all if fewer than r)."""
    if r <= 0:
        return []
    return rendezvous_rank(key, nodes)[:r]

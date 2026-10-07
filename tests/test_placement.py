"""Tests for HRW rendezvous placement (RF=2, full-file mirror)."""
from common.hashing import rendezvous_rank
from coordinator.app.services.placement import RF, rendezvous_pick

NODES = ["nodo1", "nodo2", "nodo3", "nodo4"]
KEY = "notas.txt"


def test_rank_is_deterministic():
    assert rendezvous_rank(KEY, NODES) == rendezvous_rank(KEY, NODES)


def test_known_vector_top2():
    assert rendezvous_rank(KEY, NODES) == ["nodo2", "nodo3", "nodo4", "nodo1"]
    assert rendezvous_pick(KEY, NODES) == ["nodo2", "nodo3"]


def test_pick_respects_rf():
    pick = rendezvous_pick(KEY, NODES)
    assert len(pick) == RF == 2
    assert pick == rendezvous_rank(KEY, NODES)[:2]


def test_fewer_nodes_edge():
    assert rendezvous_pick(KEY, ["nodo1", "nodo2"]) == rendezvous_rank(KEY, ["nodo1", "nodo2"])
    assert rendezvous_pick(KEY, ["nodo1"]) == ["nodo1"]
    assert rendezvous_pick(KEY, []) == []
    assert rendezvous_rank(KEY, []) == []


def test_minimal_disruption_on_removal():
    full = rendezvous_rank(KEY, NODES)
    removed = full[0]
    rest = [n for n in NODES if n != removed]
    assert rendezvous_rank(KEY, rest) == [n for n in full if n != removed]


def test_pick_is_deterministic():
    assert rendezvous_pick(KEY, NODES) == rendezvous_pick(KEY, NODES)

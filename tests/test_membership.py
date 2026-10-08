"""Tests for wave-4 heartbeat registry + failure detection + re-replication."""
import hashlib
import importlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

FAKE_NODES = ["http://n1", "http://n2", "http://n3", "http://n4"]
API_HEADERS = {"X-API-Key": "test-key"}
INTERNAL_HEADERS = {"X-Internal-Key": "test-internal"}
NODE_URLS = {
    "node-1": "http://n1",
    "node-2": "http://n2",
    "node-3": "http://n3",
    "node-4": "http://n4",
}


class FakeResponse:
    def __init__(self, status_code=200, content=b"", json_data=None):
        self.status_code = status_code
        self.content = content
        self._json = json_data if json_data is not None else {}

    def json(self):
        return self._json


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("METADATA_DB_PATH", str(tmp_path / "metadata.db"))
    monkeypatch.setenv("NODES", ",".join(FAKE_NODES))
    monkeypatch.setenv("X_INTERNAL_KEY", "test-internal")
    monkeypatch.setenv("X_API_KEY", "test-key")
    import common.http_client as http_mod
    importlib.reload(http_mod)
    import coordinator.app.services.nodes as nodes_mod
    importlib.reload(nodes_mod)
    import coordinator.app.persistence.models as models_mod
    importlib.reload(models_mod)
    import coordinator.app.services.replication as repl_mod
    importlib.reload(repl_mod)
    import coordinator.app.routers.client as client_mod
    importlib.reload(client_mod)
    import coordinator.app.routers.nodes as nodes_router_mod
    importlib.reload(nodes_router_mod)
    import coordinator.app.main as main_mod
    importlib.reload(main_mod)
    test_client = TestClient(main_mod.app)
    test_client.models = models_mod
    test_client.nodes_mod = nodes_mod
    return test_client


def _digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _old_iso(seconds: int = 3600) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _ok_fakes(monkeypatch, store: dict):
    def fake_put(url, data, headers=None):
        assert headers["X-Internal-Key"] == "test-internal"
        assert headers["X-Expected-SHA256"] == _digest(data)
        store[url] = data
        return FakeResponse(200, json_data={"sha256": _digest(data)})

    def fake_get(url, headers=None):
        if url in store:
            return FakeResponse(200, content=store[url])
        return FakeResponse(404, content=b"")

    def fake_delete(url, headers=None):
        if url in store:
            del store[url]
            return FakeResponse(200, json_data={"deleted": True})
        return FakeResponse(404, content=b"")

    import common.http_client as http_mod
    monkeypatch.setattr(http_mod, "forward_put", fake_put)
    monkeypatch.setattr(http_mod, "forward_get", fake_get)
    monkeypatch.setattr(http_mod, "forward_delete", fake_delete)


def _register_all(client):
    for node_id, base_url in NODE_URLS.items():
        r = client.post("/nodes/register",
                        json={"node_id": node_id, "base_url": base_url},
                        headers=INTERNAL_HEADERS)
        assert r.status_code == 200


def _url_to_node_id(base_url: str) -> str:
    for node_id, url in NODE_URLS.items():
        if url == base_url:
            return node_id
    raise AssertionError(f"unknown base_url {base_url!r}")


def test_register_200_and_row_echo(client):
    r = client.post("/nodes/register",
                    json={"node_id": "node-1", "base_url": "http://n1"},
                    headers=INTERNAL_HEADERS)
    assert r.status_code == 200
    row = r.json()
    assert row["node_id"] == "node-1"
    assert row["base_url"] == "http://n1"
    assert "last_seen" in row
    stored = client.models.list_nodes()
    assert any(n["node_id"] == "node-1" for n in stored)


def test_register_validation_422(client):
    assert client.post("/nodes/register",
                       json={"base_url": "http://n1"},
                       headers=INTERNAL_HEADERS).status_code == 422
    assert client.post("/nodes/register",
                       json={"node_id": "", "base_url": "http://n1"},
                       headers=INTERNAL_HEADERS).status_code == 422
    assert client.post("/nodes/register",
                       json={"node_id": "node-1"},
                       headers=INTERNAL_HEADERS).status_code == 422
    assert client.post("/nodes/register",
                       json={"node_id": "node-1", "base_url": "  "},
                       headers=INTERNAL_HEADERS).status_code == 422
    assert client.post("/nodes/heartbeat",
                       json={}, headers=INTERNAL_HEADERS).status_code == 422


def test_heartbeat_updates_last_seen(client):
    client.post("/nodes/register",
                json={"node_id": "node-1", "base_url": "http://n1"},
                headers=INTERNAL_HEADERS)
    client.models.set_last_seen("node-1", _old_iso())
    before = [n for n in client.models.list_nodes()
              if n["node_id"] == "node-1"][0]["last_seen"]
    r = client.post("/nodes/heartbeat", json={"node_id": "node-1"},
                    headers=INTERNAL_HEADERS)
    assert r.status_code == 200
    after = r.json()["last_seen"]
    assert after != before
    assert (datetime.fromisoformat(after) >
            datetime.fromisoformat(before))


def test_unknown_heartbeat_404(client):
    r = client.post("/nodes/heartbeat", json={"node_id": "ghost"},
                    headers=INTERNAL_HEADERS)
    assert r.status_code == 404
    assert "register" in r.json()["detail"].lower()


def test_get_nodes_live_dead_split_with_aged_node(client):
    _register_all(client)
    client.models.set_last_seen("node-4", _old_iso())
    r = client.get("/nodes", headers=INTERNAL_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert set(data) == {"live", "dead"}
    live_urls = {n["base_url"] if isinstance(n, dict) else n
                 for n in data["live"]}
    dead_urls = {n["base_url"] if isinstance(n, dict) else n
                 for n in data["dead"]}
    assert "http://n4" in dead_urls
    assert "http://n4" not in live_urls
    assert len(dead_urls) == 1
    assert len(live_urls) == 3


def test_get_nodes_falls_back_to_static_when_registry_empty(client):
    assert client.models.list_nodes() == []
    assert client.nodes_mod.get_nodes() == FAKE_NODES


def test_registry_nonempty_returns_only_live(client):
    _register_all(client)
    client.models.set_last_seen("node-4", _old_iso())
    assert sorted(client.nodes_mod.get_nodes()) == ["http://n1", "http://n2", "http://n3"]
    dead = client.nodes_mod.get_dead_nodes()
    assert [d["node_id"] for d in dead] == ["node-4"]


def test_is_live_single_rule_boundary(client):
    from datetime import timezone as _tz
    now = datetime.now(_tz.utc)
    fresh = now.isoformat()
    assert client.nodes_mod.is_live(fresh, now) is True
    assert client.nodes_mod.is_live(_old_iso(3600), now) is False
    assert client.nodes_mod.is_live("not-a-date", now) is False


def test_full_repair_restores_rf2_with_identical_content(client, monkeypatch):
    store = {}
    _ok_fakes(monkeypatch, store)
    _register_all(client)
    # Kill one node -> GET shows 1 dead.
    client.models.set_last_seen("node-4", _old_iso())
    assert len(client.get("/nodes", headers=INTERNAL_HEADERS).json()["dead"]) == 1
    # PUT lands RF=2 on live nodes only.
    body = b"repair-me-bytes"
    r = client.put("/files/r.txt", content=body, headers=API_HEADERS)
    assert r.status_code == 200
    assert len(r.json()["replicas"]) == 2
    assert "http://n4" not in r.json()["replicas"]
    # Kill one replica holder -> RF degraded to 1 live copy.
    victim_url = r.json()["replicas"][0]
    client.models.set_last_seen(_url_to_node_id(victim_url), _old_iso())
    # Manual repair trigger restores RF=2 with byte-identical content.
    chk = client.post("/nodes/check", headers=INTERNAL_HEADERS)
    assert chk.status_code == 200
    data = chk.json()
    assert "r.txt" in data["repaired"]
    meta = client.models.get_object("r.txt")
    assert meta is not None
    assert len(meta["replicas"]) == 2
    assert _digest(body) == meta["sha256"]
    got = client.get("/files/r.txt", headers=API_HEADERS)
    assert got.status_code == 200
    assert got.content == body
    assert _digest(got.content) == _digest(body)


def test_unrecoverable_all_holders_dead(client, monkeypatch):
    store = {}
    _ok_fakes(monkeypatch, store)
    _register_all(client)
    body = b"doomed-bytes"
    assert client.put("/files/d.txt", content=body,
                      headers=API_HEADERS).status_code == 200
    meta_before = client.models.get_object("d.txt")
    for replica_url in meta_before["replicas"]:
        client.models.set_last_seen(_url_to_node_id(replica_url), _old_iso())
    chk = client.post("/nodes/check", headers=INTERNAL_HEADERS)
    assert chk.status_code == 200
    assert "d.txt" in chk.json()["failed"]
    assert "d.txt" not in chk.json()["repaired"]
    meta_after = client.models.get_object("d.txt")
    assert meta_after == meta_before

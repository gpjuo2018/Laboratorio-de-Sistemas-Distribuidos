"""Tests for coordinator fan-out: write-2 / read-1 + SQLite metadata."""
import hashlib
import importlib

import pytest
from fastapi.testclient import TestClient

FAKE_NODES = ["http://n1", "http://n2", "http://n3", "http://n4"]
API_HEADERS = {"X-API-Key": "test-key"}


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
    monkeypatch.setenv(
        "NODES", ",".join(FAKE_NODES))
    monkeypatch.setenv("X_INTERNAL_KEY", "test-internal")
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
    import coordinator.app.main as main_mod
    importlib.reload(main_mod)
    test_client = TestClient(main_mod.app)
    test_client.models = models_mod
    return test_client


def _digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _ok_put(monkeypatch, store: dict):
    def fake_put(url, data, headers=None):
        assert headers["X-Internal-Key"] == "test-internal"
        assert headers["X-Expected-SHA256"] == _digest(data)
        store[url] = data
        return FakeResponse(200, json_data={"sha256": _digest(data)})

    def fake_get(url):
        if url in store:
            return FakeResponse(200, content=store[url])
        return FakeResponse(404, content=b"")

    def fake_delete(url):
        if url in store:
            del store[url]
            return FakeResponse(200, json_data={"deleted": True})
        return FakeResponse(404, content=b"")

    import common.http_client as http_mod
    monkeypatch.setattr(http_mod, "forward_put", fake_put)
    monkeypatch.setattr(http_mod, "forward_get", fake_get)
    monkeypatch.setattr(http_mod, "forward_delete", fake_delete)


def test_put_roundtrip_200_and_metadata_row(client, monkeypatch):
    store = {}
    _ok_put(monkeypatch, store)
    body = b"hello-coordinator"
    r = client.put("/files/a.txt", content=body, headers=API_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "a.txt"
    assert data["sha256"] == _digest(body)
    assert data["size"] == len(body)
    assert len(data["replicas"]) == 2
    row = client.models.get_object("a.txt")
    assert row is not None
    assert row["sha256"] == _digest(body)
    assert row["size"] == len(body)
    assert row["replicas"] == data["replicas"]
    assert len(store) == 2


def test_put_second_replica_fails_502_no_commit(client, monkeypatch):
    import common.http_client as http_mod

    def fake_put(url, data, headers=None):
        if url.startswith("http://n2") or "n2" in url:
            return FakeResponse(500, content=b"boom")
        return FakeResponse(200, json_data={"sha256": _digest(data)})

    # Fail exactly the second picked replica, whatever it is.
    from coordinator.app.services.placement import rendezvous_pick
    from coordinator.app.services.nodes import get_nodes
    targets = rendezvous_pick("b.txt", get_nodes())
    bad = targets[1]

    def fake_put2(url, data, headers=None):
        if url.startswith(bad):
            return FakeResponse(500, content=b"boom")
        return FakeResponse(200, json_data={"sha256": _digest(data)})

    monkeypatch.setattr(http_mod, "forward_put", fake_put2)
    r = client.put("/files/b.txt", content=b"data-b", headers=API_HEADERS)
    assert r.status_code == 502
    assert "targets" in r.json()
    assert client.models.get_object("b.txt") is None


def test_get_returns_exact_bytes(client, monkeypatch):
    store = {}
    _ok_put(monkeypatch, store)
    body = b"exact-bytes-123"
    assert client.put("/files/c.txt", content=body, headers=API_HEADERS).status_code == 200
    r = client.get("/files/c.txt", headers=API_HEADERS)
    assert r.status_code == 200
    assert r.content == body


def test_get_unknown_404(client, monkeypatch):
    _ok_put(monkeypatch, {})
    r = client.get("/files/ghost.txt", headers=API_HEADERS)
    assert r.status_code == 404


def test_get_corrupt_primary_falls_back_to_secondary(client, monkeypatch):
    import common.http_client as http_mod

    body = b"fallback-content"
    digest = _digest(body)
    from coordinator.app.services.placement import rendezvous_pick
    from coordinator.app.services.nodes import get_nodes
    targets = rendezvous_pick("d.txt", get_nodes())

    def fake_put(url, data, headers=None):
        return FakeResponse(200, json_data={"sha256": _digest(data)})

    corrupt = {f"{targets[0]}/store/d.txt": b"tampered!!!"}
    good = {f"{targets[1]}/store/d.txt": body}
    blob = {**corrupt, **good}

    def fake_get(url):
        if url in blob:
            return FakeResponse(200, content=blob[url])
        return FakeResponse(404, content=b"")

    monkeypatch.setattr(http_mod, "forward_put", fake_put)
    monkeypatch.setattr(http_mod, "forward_get", fake_get)
    assert client.put("/files/d.txt", content=body, headers=API_HEADERS).status_code == 200
    r = client.get("/files/d.txt", headers=API_HEADERS)
    assert r.status_code == 200
    assert r.content == body
    assert digest == _digest(body)


def test_get_all_corrupt_502(client, monkeypatch):
    import common.http_client as http_mod

    def fake_put(url, data, headers=None):
        return FakeResponse(200, json_data={"sha256": _digest(data)})

    def fake_get(url):
        return FakeResponse(200, content=b"garbage-everywhere")

    monkeypatch.setattr(http_mod, "forward_put", fake_put)
    monkeypatch.setattr(http_mod, "forward_get", fake_get)
    assert client.put("/files/e.txt", content=b"real", headers=API_HEADERS).status_code == 200
    r = client.get("/files/e.txt", headers=API_HEADERS)
    assert r.status_code == 502


def test_list_files(client, monkeypatch):
    store = {}
    _ok_put(monkeypatch, store)
    assert client.put("/files/f1.txt", content=b"one", headers=API_HEADERS).status_code == 200
    assert client.put("/files/f2.txt", content=b"two", headers=API_HEADERS).status_code == 200
    r = client.get("/files", headers=API_HEADERS)
    assert r.status_code == 200
    names = sorted(o["name"] for o in r.json())
    assert names == ["f1.txt", "f2.txt"]
    for o in r.json():
        assert set(o) == {"name", "sha256", "size", "replicas"}


def test_delete_removes_row_and_reports(client, monkeypatch):
    store = {}
    _ok_put(monkeypatch, store)
    assert client.put("/files/g.txt", content=b"bye", headers=API_HEADERS).status_code == 200
    r = client.delete("/files/g.txt", headers=API_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "g.txt"
    assert data["deleted"] is True
    assert len(data["replicas"]) == 2
    assert all(t["ok"] for t in data["replicas"])
    assert client.models.get_object("g.txt") is None
    assert client.get("/files/g.txt", headers=API_HEADERS).status_code == 404


def test_delete_unknown_404(client, monkeypatch):
    _ok_put(monkeypatch, {})
    r = client.delete("/files/nope.txt", headers=API_HEADERS)
    assert r.status_code == 404


def test_traversal_name_400(client, monkeypatch):
    _ok_put(monkeypatch, {})
    for bad in ["..evil", "..%5Cevil"]:
        assert client.put(f"/files/{bad}", content=b"x", headers=API_HEADERS).status_code == 400
        assert client.get(f"/files/{bad}", headers=API_HEADERS).status_code == 400
        assert client.delete(f"/files/{bad}", headers=API_HEADERS).status_code == 400


def test_missing_api_key_401(client, monkeypatch):
    _ok_put(monkeypatch, {})
    assert client.put("/files/h.txt", content=b"x").status_code == 401
    assert client.get("/files/h.txt").status_code == 401
    assert client.get("/files").status_code == 401
    assert client.delete("/files/h.txt").status_code == 401


def test_metadata_survives_reimport(client, monkeypatch, tmp_path):
    store = {}
    _ok_put(monkeypatch, store)
    body = b"persistent"
    assert client.put("/files/p.txt", content=body, headers=API_HEADERS).status_code == 200
    import coordinator.app.persistence.models as models_mod
    importlib.reload(models_mod)
    row = models_mod.get_object("p.txt")
    assert row is not None
    assert row["sha256"] == _digest(body)

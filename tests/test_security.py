"""Security matrix: X-API-Key for /files*, X-Internal-Key for internal plane.

Verifies authorized 200 vs missing 401 vs wrong 403 without exposing secrets.
No new endpoints, no business-logic changes.
"""
import importlib

import pytest
from fastapi.testclient import TestClient

API_HEADERS = {"X-API-Key": "test-key"}
INTERNAL_HEADERS = {"X-Internal-Key": "test-internal"}
WRONG_API = {"X-API-Key": "wrong-key"}
WRONG_INTERNAL = {"X-Internal-Key": "wrong-key"}


@pytest.fixture()
def coord_client(tmp_path, monkeypatch):
    monkeypatch.setenv("METADATA_DB_PATH", str(tmp_path / "metadata.db"))
    monkeypatch.setenv("NODES", "http://n1,http://n2")
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
    return TestClient(main_mod.app)


@pytest.fixture()
def node_client(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("NODE_ID", "nodo-test")
    monkeypatch.setenv("X_INTERNAL_KEY", "test-internal")
    import node.app.routers.store as store_mod
    importlib.reload(store_mod)
    import node.app.routers.peers as peers_mod
    importlib.reload(peers_mod)
    import node.app.main as node_main
    importlib.reload(node_main)
    c = TestClient(node_main.app)
    c.data_dir = data
    return c


def _no_secret_leak(resp):
    body = resp.text
    assert "test-internal" not in body
    assert "test-key" not in body


def test_files_missing_api_key_401(coord_client):
    assert coord_client.put("/files/a.txt", content=b"x").status_code == 401
    assert coord_client.get("/files/a.txt").status_code == 401
    assert coord_client.get("/files").status_code == 401
    assert coord_client.delete("/files/a.txt").status_code == 401


def test_files_wrong_api_key_403(coord_client):
    r = coord_client.put("/files/a.txt", content=b"x", headers=WRONG_API)
    assert r.status_code == 403
    _no_secret_leak(r)
    assert coord_client.get("/files/a.txt", headers=WRONG_API).status_code == 403
    assert coord_client.get("/files", headers=WRONG_API).status_code == 403
    assert coord_client.delete("/files/a.txt", headers=WRONG_API).status_code == 403


def test_files_correct_api_key_not_401_403(coord_client, monkeypatch):
    import common.http_client as http_mod

    class FakeResponse:
        status_code = 200
        content = b""
        _json = {}

        def json(self):
            return self._json

    # Avoid real network: /files list does not fan-out, must be 200.
    r = coord_client.get("/files", headers=API_HEADERS)
    assert r.status_code == 200
    _no_secret_leak(r)


def test_nodes_missing_internal_401(coord_client):
    assert coord_client.post("/nodes/register",
                             json={"node_id": "n1",
                                   "base_url": "http://n1"}).status_code == 401
    assert coord_client.post("/nodes/heartbeat",
                             json={"node_id": "n1"}).status_code == 401
    assert coord_client.get("/nodes").status_code == 401
    assert coord_client.get("/nodes/events").status_code == 401
    assert coord_client.get("/nodes/map").status_code == 401
    assert coord_client.post("/nodes/check").status_code == 401


def test_nodes_wrong_internal_403(coord_client):
    r = coord_client.post("/nodes/register",
                          json={"node_id": "n1",
                                "base_url": "http://n1"},
                          headers=WRONG_INTERNAL)
    assert r.status_code == 403
    _no_secret_leak(r)
    assert coord_client.get("/nodes",
                            headers=WRONG_INTERNAL).status_code == 403
    assert coord_client.post("/nodes/check",
                             headers=WRONG_INTERNAL).status_code == 403


def test_nodes_correct_internal_200(coord_client):
    r = coord_client.post("/nodes/register",
                          json={"node_id": "node-1",
                                "base_url": "http://n1"},
                          headers=INTERNAL_HEADERS)
    assert r.status_code == 200
    _no_secret_leak(r)
    assert coord_client.get("/nodes",
                            headers=INTERNAL_HEADERS).status_code == 200


def test_store_missing_internal_401(node_client):
    assert node_client.put("/store/a.bin",
                           content=b"x").status_code == 401
    assert node_client.get("/store/a.bin").status_code == 401
    assert node_client.delete("/store/a.bin").status_code == 401
    assert node_client.get("/internal/health").status_code == 401
    assert node_client.get("/peers").status_code == 401


def test_store_wrong_internal_403(node_client):
    r = node_client.put("/store/a.bin", content=b"x",
                        headers=WRONG_INTERNAL)
    assert r.status_code == 403
    _no_secret_leak(r)
    assert node_client.get("/store/a.bin",
                           headers=WRONG_INTERNAL).status_code == 403
    assert node_client.get("/internal/health",
                           headers=WRONG_INTERNAL).status_code == 403
    assert node_client.get("/peers",
                           headers=WRONG_INTERNAL).status_code == 403


def test_store_correct_internal_200(node_client):
    assert node_client.put("/store/a.bin", content=b"ccc",
                           headers=INTERNAL_HEADERS).status_code == 200
    r = node_client.get("/internal/health", headers=INTERNAL_HEADERS)
    assert r.status_code == 200
    _no_secret_leak(r)


def test_health_public_without_auth(coord_client, node_client):
    assert coord_client.get("/health").status_code == 200
    assert node_client.get("/health").status_code == 200

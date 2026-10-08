"""Tests for wave-5 enriched heartbeats + event log + network map + mesh."""
import hashlib
import importlib
from datetime import datetime, timedelta, timezone

import httpx
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
    test_client = TestClient(node_main.app)
    test_client.data_dir = data
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


def test_register_persists_enriched_fields(client):
    r = client.post("/nodes/register", json={
        "node_id": "node-1", "base_url": "http://n1",
        "disk_free": 123456, "files_stored": 4,
        "uptime_secs": 12.5, "version": "1.1.0",
    }, headers=INTERNAL_HEADERS)
    assert r.status_code == 200
    row = r.json()
    assert row["disk_free"] == 123456
    assert row["files_stored"] == 4
    assert row["uptime_secs"] == 12.5
    assert row["version"] == "1.1.0"
    stored = [n for n in client.models.list_nodes()
              if n["node_id"] == "node-1"][0]
    assert stored["disk_free"] == 123456
    assert stored["files_stored"] == 4
    assert stored["version"] == "1.1.0"


def test_heartbeat_persists_enriched_fields_and_preserves_omitted(client):
    assert client.post("/nodes/register",
                       json={"node_id": "node-1",
                             "base_url": "http://n1"},
                       headers=INTERNAL_HEADERS).status_code == 200
    r = client.post("/nodes/heartbeat", json={
        "node_id": "node-1", "disk_free": 999,
        "files_stored": 7, "uptime_secs": 3.25, "version": "1.1.0",
    }, headers=INTERNAL_HEADERS)
    assert r.status_code == 200
    assert r.json()["disk_free"] == 999
    assert r.json()["files_stored"] == 7
    assert r.json()["version"] == "1.1.0"
    # Bare heartbeat keeps previously reported enriched fields.
    r2 = client.post("/nodes/heartbeat", json={"node_id": "node-1"},
                     headers=INTERNAL_HEADERS)
    assert r2.status_code == 200
    assert r2.json()["disk_free"] == 999
    assert r2.json()["files_stored"] == 7


def test_revive_logs_node_up_once(client):
    client.post("/nodes/register",
                json={"node_id": "node-1", "base_url": "http://n1"},
                headers=INTERNAL_HEADERS)
    assert client.models.list_events() == []
    client.models.set_last_seen("node-1", _old_iso())
    assert client.post("/nodes/heartbeat",
                       json={"node_id": "node-1"},
                       headers=INTERNAL_HEADERS).status_code == 200
    last = client.models.last_event("node-1")
    assert last is not None and last["type"] == "node_up"
    # Fresh heartbeat afterwards logs nothing new (no dup on non-transition).
    assert client.post("/nodes/heartbeat",
                       json={"node_id": "node-1"},
                       headers=INTERNAL_HEADERS).status_code == 200
    ups = [e for e in client.models.list_events(limit=200)
           if e["type"] == "node_up" and e["node_id"] == "node-1"]
    assert len(ups) == 1


def test_events_newest_first_with_limit(client):
    client.post("/nodes/register",
                json={"node_id": "node-1", "base_url": "http://n1"},
                headers=INTERNAL_HEADERS)
    for _ in range(3):
        client.models.set_last_seen("node-1", _old_iso())
        assert client.post("/nodes/heartbeat",
                           json={"node_id": "node-1"},
                           headers=INTERNAL_HEADERS).status_code == 200
    r = client.get("/nodes/events", params={"limit": 2},
                   headers=INTERNAL_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list) and len(data) == 2
    assert data[0]["id"] > data[1]["id"]
    full = client.get("/nodes/events", headers=INTERNAL_HEADERS).json()
    assert isinstance(full, list) and len(full) == 3
    ids = [e["id"] for e in full]
    assert ids == sorted(ids, reverse=True)


def test_nodes_map_shape(client, monkeypatch):
    store = {}
    _ok_fakes(monkeypatch, store)
    _register_all(client)
    body = b"map-bytes"
    assert client.put("/files/m.txt", content=body,
                      headers=API_HEADERS).status_code == 200
    client.models.set_last_seen("node-4", _old_iso())
    r = client.get("/nodes/map", headers=INTERNAL_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert set(data) == {"coordinator", "live", "dead", "files",
                         "recent_events"}
    coord = data["coordinator"]
    assert set(coord) == {"version", "time_utc", "objects",
                          "nodes_registered"}
    assert coord["version"] == "1.1.0"
    assert coord["objects"] == 1
    assert coord["nodes_registered"] == 4
    assert len(data["live"]) == 3
    assert [n["node_id"] for n in data["dead"]] == ["node-4"]
    meta = client.models.get_object("m.txt")
    assert data["files"] == [{"name": "m.txt",
                              "replicas": meta["replicas"]}]
    assert len(data["files"][0]["replicas"]) == 2
    assert isinstance(data["recent_events"], list)


def test_check_logs_node_down_once_and_repair_summary(client, monkeypatch):
    store = {}
    _ok_fakes(monkeypatch, store)
    _register_all(client)
    body = b"doomed-then-fixed"
    assert client.put("/files/r.txt", content=body,
                      headers=API_HEADERS).status_code == 200
    victim = client.models.get_object("r.txt")["replicas"][0]
    client.models.set_last_seen(_url_to_node_id(victim), _old_iso())
    first = client.post("/nodes/check", headers=INTERNAL_HEADERS)
    assert first.status_code == 200
    assert "r.txt" in first.json()["repaired"]
    downs = [e for e in client.models.list_events(limit=200)
             if e["type"] == "node_down"
             and e["node_id"] == _url_to_node_id(victim)]
    assert len(downs) == 1
    repairs = [e for e in client.models.list_events(limit=200)
               if e["type"] == "repair"]
    assert len(repairs) == 1
    # Second check: no duplicate node_down, no extra repair (all healthy).
    second = client.post("/nodes/check", headers=INTERNAL_HEADERS)
    assert second.status_code == 200
    downs2 = [e for e in client.models.list_events(limit=200)
              if e["type"] == "node_down"
              and e["node_id"] == _url_to_node_id(victim)]
    assert len(downs2) == 1
    repairs2 = [e for e in client.models.list_events(limit=200)
                if e["type"] == "repair"]
    assert len(repairs2) == 1


def test_check_all_healthy_logs_no_repair(client, monkeypatch):
    store = {}
    _ok_fakes(monkeypatch, store)
    _register_all(client)
    assert client.put("/files/h.txt", content=b"healthy",
                      headers=API_HEADERS).status_code == 200
    chk = client.post("/nodes/check", headers=INTERNAL_HEADERS)
    assert chk.status_code == 200
    assert chk.json()["repaired"] == [] and chk.json()["failed"] == []
    assert client.models.list_events() == []


def test_node_internal_health_real_fields(node_client):
    (node_client.data_dir / "a.bin").write_bytes(b"aaa")
    (node_client.data_dir / "b.bin").write_bytes(b"bbb")
    assert node_client.put("/store/c.bin",
                           content=b"ccc",
                           headers=INTERNAL_HEADERS).status_code == 200
    r = node_client.get("/internal/health", headers=INTERNAL_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["node_id"] == "nodo-test"
    assert data["version"] == "1.1.0"
    assert data["files_stored"] == 3
    assert data["data_dir"] == str(node_client.data_dir)
    assert isinstance(data["uptime_secs"], (int, float))
    assert data["uptime_secs"] >= 0
    assert isinstance(data["disk_free"], int) and data["disk_free"] > 0


def test_node_peers_mixed_siblings(node_client, monkeypatch):
    coord = "http://coord:8000"
    monkeypatch.setenv("COORDINATOR_URL", coord)
    monkeypatch.setenv("NODE_ID", "nodo-test")
    rows = [
        {"node_id": "nodo-test", "base_url": "http://self"},
        {"node_id": "sib-ok", "base_url": "http://sib-ok"},
        {"node_id": "sib-dead", "base_url": "http://sib-dead"},
        {"node_id": "sib-500", "base_url": "http://sib-500"},
    ]

    def fake_get(url, headers=None, timeout=None):
        if url == f"{coord}/nodes":
            return FakeResponse(json_data={"live": rows[:3],
                                           "dead": rows[3:]})
        if url == "http://sib-ok/internal/health":
            return FakeResponse(json_data={"status": "ok",
                                           "version": "1.1.0"})
        if url == "http://sib-dead/internal/health":
            raise httpx.ConnectError("refused")
        if url == "http://sib-500/internal/health":
            return FakeResponse(status_code=500)
        raise AssertionError(f"unexpected url {url!r}")

    monkeypatch.setattr(httpx, "get", fake_get)
    r = node_client.get("/peers", headers=INTERNAL_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["node_id"] == "nodo-test"
    assert data["coordinator"] == {"url": coord, "reachable": True}
    by_id = {p["node_id"]: p for p in data["peers"]}
    assert set(by_id) == {"sib-ok", "sib-dead", "sib-500"}
    assert by_id["sib-ok"]["reachable"] is True
    assert by_id["sib-dead"]["reachable"] is False
    assert by_id["sib-dead"]["detail"]
    assert by_id["sib-500"]["reachable"] is False


def test_node_peers_coordinator_down_warns(node_client, monkeypatch):
    coord = "http://coord:8000"
    monkeypatch.setenv("COORDINATOR_URL", coord)
    monkeypatch.setenv("NODE_ID", "nodo-test")

    def fake_get(url, headers=None, timeout=None):
        raise httpx.ConnectError("coord down")

    monkeypatch.setattr(httpx, "get", fake_get)
    r = node_client.get("/peers", headers=INTERNAL_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["coordinator"]["reachable"] is False
    assert data["coordinator"]["url"] == coord
    assert data["peers"] == []
    assert "warning" in data


def test_peers_requires_internal_key_401_403(node_client):
    assert node_client.get("/peers").status_code == 401
    r = node_client.get("/peers",
                        headers={"X-Internal-Key": "wrong-key"})
    assert r.status_code == 403
    assert "wrong-key" not in r.text
    assert "test-internal" not in r.text


def test_peers_all_available(node_client, monkeypatch):
    coord = "http://coord:8000"
    monkeypatch.setenv("COORDINATOR_URL", coord)
    monkeypatch.setenv("NODE_ID", "nodo-test")
    rows = [
        {"node_id": "nodo-test", "base_url": "http://self"},
        {"node_id": "sib-ok", "base_url": "http://sib-ok"},
    ]

    def fake_get(url, headers=None, timeout=None):
        assert headers["X-Internal-Key"] == "test-internal"
        if url == f"{coord}/nodes":
            return FakeResponse(json_data={"live": rows[:2], "dead": []})
        if url == "http://sib-ok/internal/health":
            return FakeResponse(json_data={"status": "ok",
                                            "version": "1.1.0"})
        raise AssertionError(f"unexpected url {url!r}")

    monkeypatch.setattr(httpx, "get", fake_get)
    r = node_client.get("/peers", headers=INTERNAL_HEADERS)
    assert r.status_code == 200
    by_id = {p["node_id"]: p for p in r.json()["peers"]}
    assert by_id["sib-ok"]["reachable"] is True
    assert by_id["sib-ok"]["status"] == "available"
    assert by_id["sib-ok"]["failures"] == 0
    assert by_id["sib-ok"]["last_seen"]


def test_peers_degraded_then_disconnected(node_client, monkeypatch):
    coord = "http://coord:8000"
    monkeypatch.setenv("COORDINATOR_URL", coord)
    monkeypatch.setenv("NODE_ID", "nodo-test")
    rows = [
        {"node_id": "nodo-test", "base_url": "http://self"},
        {"node_id": "sib-flaky", "base_url": "http://sib-flaky"},
    ]

    def fake_get(url, headers=None, timeout=None):
        if url == f"{coord}/nodes":
            return FakeResponse(json_data={"live": rows[:2], "dead": []})
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", fake_get)
    first = node_client.get("/peers", headers=INTERNAL_HEADERS)
    assert first.status_code == 200
    p1 = {p["node_id"]: p for p in first.json()["peers"]}["sib-flaky"]
    assert p1["reachable"] is False
    assert p1["status"] == "degraded"
    assert p1["failures"] == 1
    second = node_client.get("/peers?refresh=true",
                             headers=INTERNAL_HEADERS)
    assert second.status_code == 200
    p2 = {p["node_id"]: p for p in second.json()["peers"]}["sib-flaky"]
    assert p2["status"] == "disconnected"
    assert p2["failures"] == 2
    assert p2["reachable"] is False


def test_peers_timeout_then_recovery(node_client, monkeypatch):
    coord = "http://coord:8000"
    monkeypatch.setenv("COORDINATOR_URL", coord)
    monkeypatch.setenv("NODE_ID", "nodo-test")
    rows = [
        {"node_id": "nodo-test", "base_url": "http://self"},
        {"node_id": "sib-t", "base_url": "http://sib-t"},
    ]
    calls = {"n": 0}

    def fake_timeout(url, headers=None, timeout=None):
        if url == f"{coord}/nodes":
            return FakeResponse(json_data={"live": rows[:2], "dead": []})
        calls["n"] += 1
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "get", fake_timeout)
    r = node_client.get("/peers", headers=INTERNAL_HEADERS)
    p = {x["node_id"]: x for x in r.json()["peers"]}["sib-t"]
    assert p["status"] == "degraded"
    assert p["detail"] == "timeout"

    def fake_ok(url, headers=None, timeout=None):
        if url == f"{coord}/nodes":
            return FakeResponse(json_data={"live": rows[:2], "dead": []})
        return FakeResponse(json_data={"status": "ok",
                                        "version": "1.1.0"})

    monkeypatch.setattr(httpx, "get", fake_ok)
    r2 = node_client.get("/peers?refresh=true", headers=INTERNAL_HEADERS)
    p2 = {x["node_id"]: x for x in r2.json()["peers"]}["sib-t"]
    assert p2["status"] == "available"
    assert p2["failures"] == 0
    assert p2["reachable"] is True
    assert p2["last_seen"]


def test_peers_node_id_mismatch(node_client, monkeypatch):
    coord = "http://coord:8000"
    monkeypatch.setenv("COORDINATOR_URL", coord)
    monkeypatch.setenv("NODE_ID", "nodo-test")
    rows = [
        {"node_id": "nodo-test", "base_url": "http://self"},
        {"node_id": "sib-x", "base_url": "http://sib-x"},
    ]

    def fake_get(url, headers=None, timeout=None):
        if url == f"{coord}/nodes":
            return FakeResponse(json_data={"live": rows[:2], "dead": []})
        return FakeResponse(json_data={"node_id": "impostor",
                                        "version": "1.1.0"})

    monkeypatch.setattr(httpx, "get", fake_get)
    r = node_client.get("/peers", headers=INTERNAL_HEADERS)
    p = {x["node_id"]: x for x in r.json()["peers"]}["sib-x"]
    assert p["reachable"] is False
    assert p["detail"] == "node_id mismatch"
    assert p["status"] == "degraded"


def test_peers_cache_ttl_and_refresh(node_client, monkeypatch):
    coord = "http://coord:8000"
    monkeypatch.setenv("COORDINATOR_URL", coord)
    monkeypatch.setenv("NODE_ID", "nodo-test")
    rows = [
        {"node_id": "nodo-test", "base_url": "http://self"},
        {"node_id": "sib-ok", "base_url": "http://sib-ok"},
    ]
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        if url == f"{coord}/nodes":
            return FakeResponse(json_data={"live": rows[:2], "dead": []})
        return FakeResponse(json_data={"status": "ok",
                                        "version": "1.1.0"})

    monkeypatch.setattr(httpx, "get", fake_get)
    first = node_client.get("/peers", headers=INTERNAL_HEADERS)
    assert first.status_code == 200
    assert first.json()["cached"] is False
    n_after_first = calls["n"]
    assert n_after_first == 2
    second = node_client.get("/peers", headers=INTERNAL_HEADERS)
    assert second.json()["cached"] is True
    # Registry is re-fetched for discovery (cheap 1 call),
    # sibling probes are cached (no extra sibling calls).
    assert calls["n"] == n_after_first + 1
    assert second.json()["peers"] == first.json()["peers"]
    third = node_client.get("/peers?refresh=true",
                            headers=INTERNAL_HEADERS)
    assert third.json()["cached"] is False
    assert calls["n"] > n_after_first + 1

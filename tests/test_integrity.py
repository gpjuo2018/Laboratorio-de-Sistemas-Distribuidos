"""Tests for SHA-256 streaming + node verified block store (requires X-Internal-Key)."""
import hashlib
import importlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from common.hashing import sha256_bytes, sha256_stream

EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
ABC_SHA = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
INTERNAL_HEADERS = {"X-Internal-Key": "test-internal"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("X_INTERNAL_KEY", "test-internal")
    os.environ["DATA_DIR"] = str(tmp_path)
    os.environ["X_INTERNAL_KEY"] = "test-internal"
    import node.app.routers.store as store_mod
    importlib.reload(store_mod)
    import node.app.main as main_mod
    importlib.reload(main_mod)
    return TestClient(main_mod.app)


def test_empty_file_vector(tmp_path):
    p = tmp_path / "empty.bin"
    p.write_bytes(b"")
    assert sha256_stream(str(p)) == EMPTY_SHA
    assert sha256_bytes(b"") == EMPTY_SHA


def test_abc_vector(tmp_path):
    p = tmp_path / "abc.bin"
    p.write_bytes(b"abc")
    assert sha256_stream(str(p)) == ABC_SHA
    assert sha256_bytes(b"abc") == ABC_SHA


def test_chunked_consistency(tmp_path):
    content = (b"0123456789abcdef" * 6400)[:100 * 1024]  # ~100KB
    p = tmp_path / "big.bin"
    p.write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()
    assert sha256_stream(str(p), chunk_size=1) == expected
    assert sha256_stream(str(p), chunk_size=7) == expected
    assert sha256_stream(str(p)) == expected


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        sha256_stream(str(tmp_path / "nope.bin"))


def _store_headers(extra=None):
    h = dict(INTERNAL_HEADERS)
    if extra:
        h.update(extra)
    return h


def test_put_roundtrip_ok(client, tmp_path):
    body = b"hello-raid1"
    digest = hashlib.sha256(body).hexdigest()
    r = client.put("/store/notas.txt", content=body,
                   headers=_store_headers({"X-Expected-SHA256": digest}))
    assert r.status_code == 200
    assert r.json() == {"name": "notas.txt", "sha256": digest, "size": len(body)}
    assert (Path(str(tmp_path)) / "notas.txt").read_bytes() == body


def test_put_wrong_hash_422_no_write(client, tmp_path):
    r = client.put("/store/bad.bin", content=b"corrupt-bytes",
                   headers=_store_headers({"X-Expected-SHA256": ABC_SHA}))
    # Auth passes (200-level would be 200), integrity fails -> 422
    assert r.status_code == 422
    assert not (Path(str(tmp_path)) / "bad.bin").exists()


def test_get_bytes_and_header(client):
    body = b"verified-content-123"
    digest = hashlib.sha256(body).hexdigest()
    assert client.put("/store/f.bin", content=body,
                      headers=_store_headers()).status_code == 200
    r = client.get("/store/f.bin", headers=INTERNAL_HEADERS)
    assert r.status_code == 200
    assert r.content == body
    assert r.headers["X-SHA256"] == digest == sha256_bytes(body)


def test_get_missing_404(client):
    r = client.get("/store/ghost.bin", headers=INTERNAL_HEADERS)
    assert r.status_code == 404
    assert r.json() == {"detail": "not found"}


def test_delete_then_get_404(client):
    assert client.put("/store/del.bin", content=b"bye",
                      headers=_store_headers()).status_code == 200
    r = client.delete("/store/del.bin", headers=INTERNAL_HEADERS)
    assert r.status_code == 200
    assert r.json() == {"name": "del.bin", "deleted": True}
    assert client.get("/store/del.bin", headers=INTERNAL_HEADERS).status_code == 404
    r2 = client.delete("/store/del.bin", headers=INTERNAL_HEADERS)
    assert r2.status_code == 404


def test_traversal_rejected(client):
    # Unit-level: the guard itself rejects ../evil and friends with 400.
    import node.app.routers.store as store_mod
    from fastapi import HTTPException
    for bad in ["../evil", "..\\evil", "..", "a/b", "a\\b", "/abs"]:
        with pytest.raises(HTTPException) as ei:
            store_mod._guard(bad)
        assert ei.value.status_code == 400
    # HTTP-level: routable single-segment evil names -> 400, nothing escapes.
    # Auth passes, guard rejects -> 400 (not 401).
    for bad in ["..evil", "..%5Cevil"]:
        assert client.put(f"/store/{bad}", content=b"x",
                          headers=_store_headers()).status_code == 400
        assert client.get(f"/store/{bad}",
                          headers=INTERNAL_HEADERS).status_code == 400
        assert client.delete(f"/store/{bad}",
                             headers=INTERNAL_HEADERS).status_code == 400


def test_guard_rejects_percent_control_empty(client):
    import node.app.routers.store as store_mod
    from fastapi import HTTPException
    for bad in ["", "   ", "a%b", "a\x01b", "a\x7fb"]:
        with pytest.raises(HTTPException) as ei:
            store_mod._guard(bad)
        assert ei.value.status_code == 400
    assert client.put("/store/%25evil", content=b"x",
                      headers=_store_headers()).status_code == 400

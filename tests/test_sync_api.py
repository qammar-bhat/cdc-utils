"""API auth + tenant scoping + job status (no live infra — Redis is faked)."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import indexer.api as api

KEY = "test-indexer-key"
AUTH = {"X-Indexer-Key": KEY}


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def set(self, k, v, ex=None):
        self.store[k] = v

    async def get(self, k):
        return self.store.get(k)


@pytest.fixture
def client(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(api, "get_redis", lambda: fake)

    async def _noop_sync(*a, **k):
        return (0, 0)

    monkeypatch.setattr(api.indexer, "sync", _noop_sync)

    app = FastAPI()
    app.include_router(api.router)   # no lifespan → no consumer / index creation
    return TestClient(app), fake


# ── auth ──────────────────────────────────────────────────────────────────────

def test_sync_requires_api_key(client):
    c, _ = client
    r = c.post("/spar/sync", json={})
    assert r.status_code == 401


def test_sync_rejects_wrong_api_key(client):
    c, _ = client
    r = c.post("/spar/sync", json={}, headers={"X-Indexer-Key": "wrong"})
    assert r.status_code == 401


def test_status_requires_api_key(client):
    c, _ = client
    assert c.get("/spar/sync/status/abc").status_code == 401


# ── tenant scoping ─────────────────────────────────────────────────────────────

def test_sync_unknown_tenant_404(client):
    c, _ = client
    r = c.post("/nope/sync", json={}, headers=AUTH)
    assert r.status_code == 404


def test_sync_unknown_tables_422(client):
    c, _ = client
    r = c.post("/spar/sync", json={"tables": ["not_a_table"]}, headers=AUTH)
    assert r.status_code == 422


def test_sync_starts_job(client):
    c, _ = client
    r = c.post("/spar/sync", json={"full_reindex": True}, headers=AUTH)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "started"
    assert body["job_id"]
    assert body["poll_url"].startswith("/spar/sync/status/")


def test_status_is_tenant_scoped(client):
    c, fake = client
    # A job owned by dev_env must 404 when polled under spar.
    fake.store["sync_job:job1"] = json.dumps({
        "job_id": "job1", "status": "ok", "started_at": "now", "client_id": "dev_env",
    })
    assert c.get("/dev_env/sync/status/job1", headers=AUTH).status_code == 200
    assert c.get("/spar/sync/status/job1", headers=AUTH).status_code == 404


def test_status_missing_job_404(client):
    c, _ = client
    assert c.get("/spar/sync/status/ghost", headers=AUTH).status_code == 404


# ── root is gated; health is open ─────────────────────────────────────────────

def test_root_requires_api_key(client):
    c, _ = client
    assert c.get("/").status_code == 401


def test_root_with_key_ok(client):
    c, _ = client
    r = c.get("/", headers=AUTH)
    assert r.status_code == 200
    assert "tenants" in r.json()

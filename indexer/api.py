"""api.py — internal indexer API (NOT exposed to client end-users).

Routes (callers are DevOps / admin tooling, authenticated with a static
service token, not JWTs):

    POST /{client_id}/sync               start a background sync job
    GET  /{client_id}/sync/status/{job_id}   poll a job (tenant-scoped)
    GET  /health                         OpenSearch + per-tenant DB + consumer
    GET  /                               service / version

Auth: every route except `/` and `/health` requires the `X-Indexer-Key` header
to match the INDEXER_API_KEY env var.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid as uuid_lib
from datetime import datetime, timezone

import logfire
from fastapi import APIRouter, Depends, Header, HTTPException

from indexer import __doc__ as _service_doc  # noqa: F401
from indexer.config import get_redis
from indexer.consumer import cdc_consumer
from indexer.db import get_engine
from indexer.doc_types import indices_for
from indexer.indexing import indexer
from indexer.models import SyncJobResponse, SyncJobStatus, SyncRequest
from indexer.os_client import get_opensearch_client
from indexer.registry.overrides import resolve_registry
from indexer.tenants import UnknownTenantError, all_tenants, debezium_host_groups, get_tenant
from indexer.tracing import trace_context

router = APIRouter()

SERVICE_NAME = "erpforce-indexer"
SERVICE_VERSION = os.environ.get("SERVICE_VERSION", "0.1.0")

_INDEXER_API_KEY = os.environ.get("INDEXER_API_KEY", "")


# ---------------------------------------------------------------------------
# Auth + tenant dependencies
# ---------------------------------------------------------------------------

def require_api_key(x_indexer_key: str | None = Header(default=None)) -> None:
    """Reject any request whose X-Indexer-Key does not match INDEXER_API_KEY."""
    if not _INDEXER_API_KEY:
        # Fail closed: a missing server-side key means the service is misconfigured,
        # not that auth is disabled.
        raise HTTPException(status_code=503, detail="INDEXER_API_KEY is not configured")
    if x_indexer_key != _INDEXER_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Indexer-Key")


def require_tenant(client_id: str):
    """Resolve client_id to a TenantConfig or 404."""
    try:
        return get_tenant(client_id)
    except UnknownTenantError:
        raise HTTPException(status_code=404, detail=f"Unknown client '{client_id}'")


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

@router.post(
    "/{client_id}/sync",
    response_model=SyncJobResponse,
    status_code=202,
    summary="Start a background re-index of this client's ERP data into OpenSearch",
    dependencies=[Depends(require_api_key)],
)
async def sync_index(client_id: str, req: SyncRequest) -> SyncJobResponse:
    tenant = require_tenant(client_id)

    reg = resolve_registry(tenant.client_id)  # this tenant's table set (base + overrides)
    if req.tables:
        unknown = [t for t in req.tables if t not in reg]
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown tables for '{tenant.client_id}': {unknown}")

    job_id = str(uuid_lib.uuid4())

    redis = get_redis()
    initial = SyncJobStatus(
        job_id=job_id,
        status="running",
        total_tables=len(req.tables) if req.tables else len(reg),
        started_at=datetime.now(timezone.utc).isoformat(),
    ).model_dump()
    initial["client_id"] = tenant.client_id
    await redis.set(f"sync_job:{job_id}", json.dumps(initial), ex=3600)

    async def _traced_sync(cid=tenant.client_id):
        # trace_context wraps the whole job so every span is tagged client:<id>
        # in Langfuse (tenant-filterable in the shared project).
        with trace_context(client_id=cid, service="indexer-sync", job_id=job_id):
            await indexer.sync(
                client_id=cid,
                tables=req.tables,
                full_reindex=req.full_reindex,
                recreate_indices=req.recreate_indices,
                job_id=job_id,
            )

    asyncio.create_task(_traced_sync())

    return SyncJobResponse(
        job_id=job_id,
        status="started",
        poll_url=f"/{tenant.client_id}/sync/status/{job_id}",
    )


@router.get(
    "/{client_id}/sync/status/{job_id}",
    response_model=SyncJobStatus,
    summary="Poll the status of a background sync job (tenant-scoped)",
    dependencies=[Depends(require_api_key)],
)
async def sync_status(client_id: str, job_id: str) -> SyncJobStatus:
    tenant = require_tenant(client_id)
    redis = get_redis()
    raw = await redis.get(f"sync_job:{job_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found or expired (TTL: 1 hour)")
    payload = json.loads(raw)
    # Tenant-scoped: a job belongs only to the client that started it.
    if payload.get("client_id") and payload["client_id"] != tenant.client_id:
        raise HTTPException(status_code=404, detail="Job not found or expired (TTL: 1 hour)")
    payload.pop("client_id", None)
    return SyncJobStatus(**payload)


# ---------------------------------------------------------------------------
# Health / root
# ---------------------------------------------------------------------------

@router.get("/health", summary="OpenSearch ping + per-tenant DB pings + consumer alive")
async def health() -> dict:
    loop = asyncio.get_running_loop()
    checks: dict[str, object] = {}

    # OpenSearch
    try:
        client = get_opensearch_client()
        ok = await loop.run_in_executor(None, client.ping)
        checks["opensearch"] = "ok" if ok else "down"
    except Exception as exc:
        checks["opensearch"] = f"down: {exc}"

    # Per-tenant DB pings
    db_status: dict[str, str] = {}
    for tenant in all_tenants():
        try:
            from sqlalchemy import text

            def _ping(cid=tenant.client_id):
                with get_engine(cid).connect() as conn:
                    conn.execute(text("SELECT 1"))

            await loop.run_in_executor(None, _ping)
            db_status[tenant.client_id] = "ok"
        except Exception as exc:
            db_status[tenant.client_id] = f"down: {exc}"
    checks["databases"] = db_status

    # CDC consumer thread
    alive = cdc_consumer._thread is not None and cdc_consumer._thread.is_alive()
    checks["cdc_consumer"] = "alive" if alive else "stopped"

    # Debezium liveness — Quarkus readiness reflects connector state, so a stuck
    # producer (e.g. the binlog-purged "Error 1236" loop, which emits ZERO
    # events and is otherwise invisible from the consumer side) shows up here.
    # One Debezium instance covers every tenant on the same physical DB host
    # (see debezium_host_groups()), so it's probed once per host-group and the
    # single result is fanned out to every member tenant's client_id key —
    # keeps the existing per-tenant JSON shape without redundant duplicate pings.
    # Skipped when DEBEZIUM_HEALTH_CHECK is disabled (e.g. Debezium managed elsewhere).
    dbz_status: dict[str, str] = {}
    if os.environ.get("DEBEZIUM_HEALTH_CHECK", "true").lower() in ("1", "true", "yes"):
        import urllib.request

        tmpl = os.environ.get(
            "DEBEZIUM_HEALTH_URL_TEMPLATE",
            "http://debezium-{group_id}:8080/q/health/ready",
        )

        def _dbz_ping(url):
            with urllib.request.urlopen(url, timeout=5) as r:
                return r.status == 200

        for group_id, members in debezium_host_groups().items():
            url = tmpl.format(group_id=group_id)
            try:
                ok = await loop.run_in_executor(None, _dbz_ping, url)
                result = "ok" if ok else "down"
            except Exception as exc:
                result = f"unreachable: {exc}"
            for tenant in members:
                dbz_status[tenant.client_id] = result
        checks["debezium"] = dbz_status

    # Per-tenant CDC stream lag — sum of group-unread + pending across that
    # tenant's streams. A steadily climbing number means the consumer can't keep
    # up (or is wedged); surfaced here for alerting, not a hard failure.
    try:
        lag = _cdc_lag_by_tenant()
        if lag:
            checks["cdc_lag"] = lag
    except Exception as exc:
        checks["cdc_lag"] = f"unavailable: {exc}"

    # The indexer itself is healthy if ITS dependencies are up. A down Debezium
    # is reported as "degraded" (alert-worthy) but must NOT mark the indexer
    # unhealthy — that would trigger pointless restarts of a working service.
    core_ok = (
        checks["opensearch"] == "ok"
        and all(v == "ok" for v in db_status.values())
        and checks["cdc_consumer"] == "alive"
    )
    producers_ok = all(v == "ok" for v in dbz_status.values()) if dbz_status else True
    if not core_ok:
        status = "unhealthy"
    elif not producers_ok:
        status = "degraded"
    else:
        status = "ok"
    if status != "ok":
        logfire.warning("indexer health not ok", status=status, checks=checks)
    return {"status": status, "checks": checks}


def _cdc_lag_by_tenant() -> dict[str, int]:
    """Best-effort total CDC backlog per tenant (group-unread + pending).

    Uses a short-lived synchronous Redis client so a health probe can't disturb
    the consumer's connection. Returns {} if Redis is unreachable.
    """
    import redis as _redis

    from indexer.consumer import _GROUP_NAME, _build_stream_map
    from indexer.config import settings

    r = _redis.from_url(settings.redis_url, decode_responses=True, protocol=2, socket_connect_timeout=3)
    try:
        per_tenant: dict[str, int] = {}
        for stream, client_id in _build_stream_map().items():
            try:
                groups = r.xinfo_groups(stream)
            except _redis.exceptions.ResponseError:
                continue  # stream/group not created yet
            for g in groups:
                if g.get("name") == _GROUP_NAME:
                    per_tenant[client_id] = per_tenant.get(client_id, 0) + int(g.get("lag") or 0) + int(g.get("pending") or 0)
        return per_tenant
    finally:
        try:
            r.close()
        except Exception:
            pass


@router.get("/", summary="Service / version", dependencies=[Depends(require_api_key)])
async def root() -> dict:
    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "tenants": [t.client_id for t in all_tenants()],
        "indices_per_tenant": len(indices_for("_")),
    }

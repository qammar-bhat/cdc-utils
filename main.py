"""main.py — erpforce-indexer service entrypoint.

Run:
    uvicorn main:app --host 0.0.0.0 --port 8090

Lifespan (in order):
  1. Load the tenant registry — fail fast on bad/missing client config.
  2. Log the embedding (model, dimension) — LOCK-STEP CONTRACT #1 with the hub.
  3. Create each tenant's module indices (idempotent) + the hybrid-search pipeline.
  4. Warm the embedding model so the first CDC event isn't slow.
  5. Start the Redis Streams CDC consumer (consumer group: smart-search-cdc).

On shutdown the consumer is stopped cleanly.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import logfire
from fastapi import FastAPI

from indexer.api import router
from indexer.config import settings
from indexer.consumer import cdc_consumer
from indexer.doc_types import indices_for
from indexer.embedder import embedder
from indexer.indexing import indexer
from indexer.os_client import get_opensearch_client
from indexer.tenants import all_tenants
from indexer.tracing import build_langfuse_processors

logfire.configure(
    service_name="erpforce-indexer",
    send_to_logfire="if-token-present",   # exports to Logfire cloud when LOGFIRE_TOKEN is set
    # console left at its default (enabled) so consumer/sync activity prints to
    # the container log, mirroring the hub.
    additional_span_processors=build_langfuse_processors(),  # → Langfuse (OTel), per-tenant tagged
)

# Surface stdlib logging (consumer.py uses logging.getLogger) to the console too.
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))


def _check_embedding_dim_drift(expected_dim: int, tenants) -> None:
    """Compare each existing index's vector dimension to our embedding model's.

    A mismatch means the index was built with a different model — kNN search is
    silently broken. Logs an ERROR per drifted index (cheap alarm; does not crash
    so the service can still serve the sync API to rebuild the index).
    """
    client = get_opensearch_client()
    for tenant in tenants:
        for index in indices_for(tenant.client_id):
            try:
                if not client.indices.exists(index=index):
                    continue
                mapping = client.indices.get_mapping(index=index)
                props = mapping[index]["mappings"].get("properties", {})
                live_dim = props.get("embedding", {}).get("dimension")
                if live_dim is not None and int(live_dim) != int(expected_dim):
                    logfire.error(
                        "EMBEDDING DIMENSION DRIFT — kNN search is broken for this index. "
                        "Re-sync with recreate_indices=true after aligning llm_profiles.json.",
                        index=index,
                        live_dimension=live_dim,
                        model_dimension=expected_dim,
                    )
            except Exception as exc:
                logfire.warning("embedding drift check failed", index=index, error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Fail fast on tenant config
    tenants = all_tenants()
    logfire.info("indexer tenants loaded", tenants=[t.client_id for t in tenants])

    # 2. Embedding profile — must match the hub's (LOCK-STEP CONTRACT #1)
    emb = settings.resolve_embedding_runtime()
    logfire.info(
        "indexer embedding profile",
        provider=emb["provider"],
        model=emb["model"],
        dimension=emb["dimension"],
    )

    # 3. Per-tenant indices + hybrid-search pipeline (idempotent)
    for tenant in tenants:
        try:
            await indexer.create_indices(tenant.client_id)
            logfire.info("indexer indices ready", client_id=tenant.client_id)
        except Exception as exc:
            logfire.error("indexer index creation failed", client_id=tenant.client_id, error=str(exc))

    # 3b. Embedding-dimension drift guard (LOCK-STEP CONTRACT #1).
    # If a live index's vector dimension != our embedding model's dimension,
    # kNN search is silently broken (vectors in different spaces). Fail LOUD.
    _check_embedding_dim_drift(emb["dimension"], tenants)

    # 4. Warm the embedding model
    try:
        await embedder.embed_many(["warmup"])
        logfire.info("indexer embedder warmed")
    except Exception as exc:
        logfire.warning("indexer embedder warmup failed", error=str(exc))

    # 5. Start CDC consumer
    cdc_consumer.start()

    try:
        yield
    finally:
        cdc_consumer.stop()


app = FastAPI(
    title="erpforce-indexer",
    description="Multi-tenant CDC/indexing service — owns the OpenSearch write path.",
    version=os.environ.get("SERVICE_VERSION", "0.1.0"),
    lifespan=lifespan,
)
app.include_router(router)

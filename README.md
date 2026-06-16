# erpforce-indexer

Multi-tenant CDC / indexing microservice. One deployment owns the entire
OpenSearch **write** path for **all** clients: per-tenant index creation, bulk
sync, and CDC consumption. The hub (`erpforce-ai-hub-v2`) becomes read-only on
OpenSearch.

> Repo folder is `cdc-utils`; the Python package and service are `indexer` /
> `erpforce-indexer`.

## Layout

```
cdc-utils/
├── main.py                 # FastAPI app + lifespan (tenants → indices → embedder → consumer)
├── llm_profiles.json       # embedding profile ONLY (LOCK-STEP CONTRACT #1 with the hub)
├── requirements.txt / pyproject.toml
├── Dockerfile / docker-compose.yaml   # standalone; connects to infra by address from .env
├── scripts/gen_debezium.py            # renders one Debezium Server per tenant
├── .env.example
├── indexer/
│   ├── tenants.py          # tenant registry (TENANT_IDS + {ID}_APPLICATION_DB_*)
│   ├── config.py           # redis url, OpenSearch creds, embedding profile loader, get_redis
│   ├── db.py               # per-tenant read-only SQLAlchemy engines + keyword guard
│   ├── embedder.py         # bedrock / fastembed / openai embeddings
│   ├── os_client.py        # OpenSearch client singleton
│   ├── registry/           # the 45 tables: SQL, doc builders, modules
│   ├── doc_types.py        # index_for / indices_for / ALL_MODULES (source of truth HERE)
│   ├── indexing.py         # mappings, create/recreate_indices, sync(), job status, pipeline
│   ├── cdc_handler.py      # per-event upsert/delete (refetch row → embed → bulk)
│   ├── consumer.py         # Redis Streams consumer (group: smart-search-cdc)
│   └── api.py              # FastAPI routes
├── debezium/application.properties.example   # per-client Debezium Server template
└── tests/
```

## API (internal only — DevOps/admin tooling, not client end-users)

Auth: static `X-Indexer-Key` header checked against `INDEXER_API_KEY`.

| Route | What |
|---|---|
| `POST /{client_id}/sync` | start a background sync (`tables` / `full_reindex` / `recreate_indices`) |
| `GET /{client_id}/sync/status/{job_id}` | poll a job (tenant-scoped; 404 cross-tenant) |
| `GET /health` | OpenSearch ping + per-tenant DB pings + consumer-thread alive |
| `GET /` | service / version / tenants |

Example:

```bash
curl -X POST http://localhost:8090/spar/sync \
  -H "X-Indexer-Key: $INDEXER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"full_reindex": true}'
```

`full_reindex: true` deletes each table's docs then re-adds only live
(`is_deleted = 0`) rows — this is what clears orphaned documents. Use
`recreate_indices: true` only when the embedding dimension changes.

## Env contract

See [.env.example](.env.example). Tenant + shared-infra values must match the
hub (same DBs, same Redis, same OpenSearch).

## The two LOCK-STEP CONTRACTS with the hub

1. **Embedding profile** — `llm_profiles.json` `embedding_profile` (model +
   dimension) MUST be identical in both repos. A mismatch silently breaks kNN
   search (vectors live in different spaces). Both services log
   `(model, dimension)` at startup.
2. **`doc_type → module` map** — this repo's `registry` is the source of truth;
   the hub's slim `doc_types.py` is a hand-copy. **Adding a table = touch both
   repos.**

## Independence from the hub

This repo has **no code, network, or container dependency** on `erpforce-ai-hub-v2`:

- **Code:** zero imports from the hub package (verified). The `indexer` package is self-contained.
- **Infra:** Redis / OpenSearch / MySQL are reached purely by address from `.env`.
  Compose does not join the hub's project or network. Attach to shared infra by
  name via `INFRA_NETWORK` / `INFRA_NETWORK_EXTERNAL`, or point at managed
  endpoints by DNS/IP.
- **CDC producer:** Debezium is **owned here** (see below), not borrowed from the hub.

The only intentional coupling is a **data contract**, documented in both repos:
the embedding profile (LOCK-STEP CONTRACT #1) and the `doc_type→module` map.

## CDC pipeline (Debezium owned here)

One **Debezium Server per tenant** (`topic.prefix=cdc_{client_id}`), generated
from `TENANT_IDS` + the indexer registry so captured tables can't drift from
indexed tables:

```bash
python scripts/gen_debezium.py        # → docker-compose.debezium.yml
docker compose -f docker-compose.yaml -f docker-compose.debezium.yml up -d
```

Stream key is `{topic_prefix}.{db_name}.{table}`; the consumer maps it back to
the tenant by prefix (db names collide across clients). Consumer group:
`smart-search-cdc`. See [debezium/README.md](debezium/README.md).

## Observability (Logfire + Langfuse)

Same stack as the hub:
- **Logfire** is the primary APM. Structured logs + spans (`sync`, CDC batches,
  OpenSearch bulk, DB queries) always print to the container console; they also
  ship to Logfire cloud when `LOGFIRE_TOKEN` is set.
- **Langfuse** receives the same spans via OTLP (`indexer/tracing.py`), tagged
  `client:<tenant>` so one tenant's CDC/sync activity is filterable in the shared
  project. Enabled when `LANGFUSE_BASE_URL` + `LANGFUSE_PUBLIC_KEY` +
  `LANGFUSE_SECRET_KEY` are set; omit them to disable export (service still runs).

No `LangchainInstrumentor` here — the indexer makes no LLM calls (embeddings are
local/fastembed or boto3), so there's a single Langfuse project, not the hub's
API/LLM split. Set the env keys in `.env` (see `.env.example`).

## Production hardening

- **Auth:** `INDEXER_API_KEY` required (fails closed if unset). `/` and the sync
  routes are gated; `/health` is open for orchestration probes.
- **Health (`GET /health`):** OpenSearch ping, per-tenant DB ping, consumer
  thread, **per-tenant Debezium readiness**, and **per-tenant CDC lag**. A down
  Debezium reports `degraded` (alert-worthy) without marking the indexer
  unhealthy. Status is `ok` / `degraded` / `unhealthy`.
- **Embedding-dimension drift guard:** at startup the live index vector dimension
  is compared to the model's; a mismatch logs a loud `ERROR` (kNN would be silently broken).
- **CDC consumer is supervised:** a session is kept alive across ANY failure,
  including *startup* failures (Redis down at boot) — the thread can't die
  permanently and silently stop CDC. Steady-state errors retry with backoff +
  client rebuild (survives Docker DNS blips); dead-letter after 5 attempts.
- **Reproducible builds:** dependencies are pinned (`requirements.txt`); the
  embedding model is baked into the image before source copy (cached across code changes).
- **Resource caps:** `mem_limit` / `cpus` on the indexer and every Debezium
  (override via `*_MEM_LIMIT` / `*_CPUS` env).
- **Container health + restart:** compose `healthcheck` + `restart: unless-stopped`
  on the indexer and every Debezium instance.
- **CI:** `.github/workflows/ci.yml` — byte-compile + pytest + generator smoke on every PR.

## Runbook — Debezium stuck ("Error 1236", captures nothing)

Symptom: a table change never appears in OpenSearch; the stream
`cdc_<tenant>.<db>.<table>` stays empty; Debezium logs
`Could not find first log file name in binary log index file (Error 1236)`.

Cause: MySQL purged the binlog past Debezium's saved offset (downtime >
`binlog_expire_logs_seconds`, or a DB restore). Debezium can't resume.

Fix (reset that tenant's Debezium offset; it resumes at the current binlog tail):

```bash
docker compose -f docker-compose.debezium.yml stop debezium-<tenant>
docker run --rm -v <project>_debezium_<tenant>_data:/data alpine \
  rm -f /data/offsets.dat /data/schema-history.dat
docker compose -f docker-compose.debezium.yml start debezium-<tenant>
```

With `DEBEZIUM_SNAPSHOT_MODE=no_data` it resumes from *now* (no backfill); run
`POST /{tenant}/sync {"full_reindex": true}` to backfill existing rows.

**Prevent recurrence:** set MySQL `binlog_expire_logs_seconds` larger than your
worst-case Debezium downtime (≥7 days recommended), and watch `/health`
`cdc_lag` + `debezium` status.

## Develop / test

```bash
pip install -e ".[dev]"
pytest                                  # unit tests run with no live infra
python scripts/gen_debezium.py          # render per-tenant Debezium compose
uvicorn main:app --host 0.0.0.0 --port 8090
```

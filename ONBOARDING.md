# Onboarding a new tenant

How to add a new client/tenant to the erpforce-indexer (CDC → OpenSearch).

> Example below uses client id **`acme`**. Replace with your real id (lowercase,
> matches `^[a-z][a-z0-9_]{1,30}$`). Steps 1–4 are setup; 5–7 bring it live.

The indexer owns the **write/CDC path** only. If the hub copilot must also answer
for this tenant, that's a separate step on the hub side (its own tenant env + JWT).

---

## At a glance

| Step | Where | Required? |
|---|---|---|
| 1. `.env` tenant block | config | ✅ always |
| 2. MySQL binlog + Debezium user | client DB | ✅ always |
| 3. `tenants/<id>.py` schema override | code | only if schema differs from base |
| 4. Regenerate Debezium | `scripts/gen_debezium.py` | ✅ always |
| 5. Bring up (restart indexer + Debezium) | infra | ✅ always |
| 6. Backfill existing rows | `POST /<id>/sync` | ✅ for existing data |
| 7. Verify | `/health`, index counts | ✅ always |

---

## 1. Add the tenant to `.env`

Append the id to `TENANT_IDS` and add its block (mirror the existing `SPAR_*`):

```bash
TENANT_IDS=spar,dev_env,acme

ACME_APPLICATION_DB_HOST=mysql            # client's MySQL host (or shared 'mysql')
ACME_APPLICATION_DB_PORT=3306
ACME_APPLICATION_DB_NAME=acme_prod
ACME_APPLICATION_DB_USER=application_db   # READ-ONLY user the indexer queries with
ACME_APPLICATION_DB_PASSWORD=<secret>
ACME_APPLICATION_DB_POOL_SIZE=3
ACME_APPLICATION_DB_MAX_OVERFLOW=7
ACME_CDC_TOPIC_PREFIX=cdc_acme            # see note below — depends on host sharing
```

The tenant registry **fails fast** at startup if any required var is missing — a
half-configured tenant can never serve traffic.

**`CDC_TOPIC_PREFIX` depends on whether this tenant shares a DB host:**

- **Colocating on an existing host** (e.g. another tenant already uses
  `ACME_APPLICATION_DB_HOST=mysql`) — one Debezium instance serves the whole
  host, so `ACME_CDC_TOPIC_PREFIX` **must equal** the value the other tenant(s)
  on that host already use. A mismatch raises `TenantConfigError` at boot. You
  do **not** need new `CDC_DB_USER`/`CDC_DB_PASSWORD` vars — the existing
  host-group credential already covers it (just grant it `SELECT` on
  `acme_prod` too, see step 2).
- **A new, dedicated host** — pick any prefix unique from every other host
  group's prefix, and add group-scoped credentials (see step 2) for the new
  group.

Either way, `(topic_prefix, db_name)` as a pair must stay unique across all tenants.

## 2. MySQL prerequisites (on the client's database)

- Binary logging in ROW mode:
  ```
  binlog_format=ROW
  binlog_row_image=FULL
  ```
- A Debezium user with replication rights:
  - **Colocating on an existing host** — the host's existing Debezium user
    already has `REPLICATION SLAVE`/`REPLICATION CLIENT` globally; just extend
    its `SELECT` grant to the new database:
    ```sql
    GRANT SELECT ON acme_prod.* TO 'debezium'@'%';
    ```
  - **New dedicated host** — create the user and set
    `{GROUP_ID}_CDC_DB_USER` / `{GROUP_ID}_CDC_DB_PASSWORD` in `.env`
    (`GROUP_ID` = `debezium_group_id(db_host, db_port)` from `indexer/tenants.py`,
    e.g. `mysql_3306`):
    ```sql
    CREATE USER 'debezium'@'%' IDENTIFIED BY '<secret>';
    GRANT REPLICATION SLAVE, REPLICATION CLIENT, SELECT ON *.* TO 'debezium'@'%';
    ```
- **Binlog retention longer than worst-case Debezium downtime**
  (`binlog_expire_logs_seconds >= 604800`, i.e. 7 days). If binlogs are purged
  past Debezium's saved offset it gets stuck on `Error 1236` and silently captures
  nothing — see the recovery runbook in [README](README.md#runbook).

## 3. (Optional) Schema customizations

Tenants share the ~90% base registry. **Only if** this tenant's schema diverges
(a column/table differs or is absent), create `indexer/registry/tenants/acme.py`:

```python
"""Registry overrides for tenant `acme`."""
from __future__ import annotations

OVERRIDES: dict[str, dict | None] = {
    # replace only the SQL, inherit the rest:
    "some_table": {"sql": "SELECT t.*, ... FROM some_table t WHERE t.is_deleted = 0"},
    # tenant doesn't have this table at all:
    "table_they_lack": None,
    # a table only this tenant has (give it a module so doc_types can map it):
    # "acme_only_table": {"index": "erpforce_sales", "module": "sales", "sql": "...", ...},
}
```

If `acme` runs a vanilla erpforce schema, **skip this** — they inherit the base
registry automatically (no file needed). At startup the indexer logs exactly
what each tenant overrode/dropped/added, and warns on a likely typo'd table name.

## 4. Regenerate Debezium

```bash
python scripts/gen_debezium.py
```

Re-reads `TENANT_IDS` + the registry and rewrites `docker-compose.debezium.yml`.
If `acme` colocates on an existing host, its tables are folded into that
host's existing `debezium-<group_id>` service (no new container) — check the
script's printed output to confirm `acme` shows up under the right group. If
it's on a new dedicated host, a new `debezium-<group_id>` service appears with
its own `server.id` and offset/schema volume.

## 5. Bring it up

```bash
docker compose -f docker-compose.yaml -f docker-compose.debezium.yml up -d
```

- The indexer is **recreated** (because `.env` changed) → it reloads the tenant
  registry and rebuilds the CDC consumer's stream map to subscribe to
  `<acme's topic_prefix>.acme_prod.*`.
- On boot, lifespan auto-creates `acme_account`, `acme_sales`, … indices + the
  search pipeline.
- The host-group's Debezium instance starts tailing `acme_prod`'s tables (or
  keeps tailing, if colocated on an already-running host) → live changes flow
  immediately.

## 6. Backfill existing rows

CDC (`DEBEZIUM_SNAPSHOT_MODE=no_data`) captures changes from *now*. To index data
already in the DB, run a full reindex:

```bash
curl -X POST http://localhost:8090/acme/sync \
  -H "X-Indexer-Key: $INDEXER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"full_reindex": true}'
```

Returns a `job_id` + `poll_url`. Poll until `status: ok`:

```bash
curl -s http://localhost:8090/acme/sync/status/<job_id> -H "X-Indexer-Key: $INDEXER_API_KEY"
```

## 7. Verify

```bash
# health: acme's DB ping + its host-group's debezium readiness should be "ok"
curl -s http://localhost:8090/health -H "X-Indexer-Key: $INDEXER_API_KEY"

# spot-check an index has docs
curl -s "$OPENSEARCH/acme_account/_count"
```

End-to-end smoke test: insert/update a row in acme's MySQL → within a few seconds
it appears in `acme_<module>` (watch the indexer log for
`smart_search CDC batch upsert`).

---

## Removing a tenant

Drop the id from `TENANT_IDS`, regenerate Debezium, and `up -d`. Their data and
indices remain until manually deleted (removal is reversible). If they were the
**last** tenant on their DB host, that host's `debezium-<group_id>` service
disappears from the regenerated compose file — optionally delete the
`debezium_<group_id>_data` volume to reclaim space (only if no other tenant
still shares that host). Also delete the `acme_*` indices if reclaiming space.

## Common pitfalls

- **Mismatched `CDC_TOPIC_PREFIX` on a shared host** → startup error (tenants on
  the same host must agree, since one connector has one `topic.prefix`).
- **Forgot to restart the indexer** → new streams aren't consumed (the stream map
  is built at startup).
- **No backfill** → only post-onboarding changes appear; run `POST /<id>/sync`.
- **Debezium user lacks `REPLICATION`/`SELECT` grants** → `debezium-<group_id>`
  crash-loops for **every tenant on that host**, not just the new one; check
  `docker logs debezium-<group_id>`.
- **Binlog retention too short** → `Error 1236` after any downtime, breaking
  CDC for every tenant on that host; see README runbook.

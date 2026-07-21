# Debezium (CDC producer) — owned by this repo

CDC is multi-tenant: **one Debezium Server per physical DB host**, not per
tenant. Debezium Server is single-source-per-instance, but that limit is per
*binlog connection* — tenants sharing a `(db_host, db_port)` already share one
binlog stream, so they share one Debezium Server container; a tenant on its
own dedicated host still gets its own. We don't hand-maintain these — they're
generated from the same sources the indexer uses, so the captured tables can
never drift from the indexed tables.

## Generate + run

```bash
python scripts/gen_debezium.py        # → docker-compose.debezium.yml (one debezium-<group_id> per DB host)
docker compose -f docker-compose.yaml -f docker-compose.debezium.yml up -d
```

Regenerate whenever you **add/remove a tenant** (`TENANT_IDS`) or **add a table**
to `indexer/registry/`.

## What each instance does

- Reads that DB host's MySQL binlog, authenticating as one shared CDC user per
  group (`{GROUP_ID}_CDC_DB_USER`, needing `REPLICATION SLAVE, REPLICATION
  CLIENT` globally + `SELECT` on every tenant db on that host — not the
  per-tenant `{ID}_APPLICATION_DB_USER`, which is unrelated and stays scoped to
  the indexer's own queries).
- `database.include.list` / `table.include.list` cover every tenant db + table
  on that host in one connector config.
- Emits to Redis streams `{topic_prefix}.{db}.{table}` — exactly what the
  indexer consumer subscribes to. Every tenant sharing a host MUST use the
  same `CDC_TOPIC_PREFIX` (enforced at boot in `indexer/tenants.py`), since one
  connector has exactly one `topic.prefix`; the consumer still tells tenants
  apart by `db_name`, which stays unique.
- Unique `database.server.id`, one shared offset + schema-history volume per
  host group (one physical binlog = one offset position — this was never
  meaningful per-tenant).
- Exposes Quarkus health on `:8080` (`/q/health/ready`) — the indexer's
  `/health` pings it once per group and reports the result under every member
  tenant's `client_id`, so a stuck connector is still visible per-tenant.

## MySQL prerequisites

- `binlog_format=ROW`, `binlog_row_image=FULL`.
- **Binlog retention longer than worst-case Debezium downtime.** If binlogs are
  purged past Debezium's saved offset it gets stuck on `Error 1236` and captures
  nothing — for **every tenant on that host**, not just one. See the recovery
  runbook in the top-level [README](../README.md#runbook).

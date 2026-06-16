# Debezium (CDC producer) — owned by this repo

CDC is multi-tenant: **one Debezium Server per tenant** (Debezium Server is
single-source-per-instance). We don't hand-maintain these — they're generated
from the same sources the indexer uses, so the captured tables can never drift
from the indexed tables.

## Generate + run

```bash
python scripts/gen_debezium.py        # → docker-compose.debezium.yml (one debezium-<tenant> each)
docker compose -f docker-compose.yaml -f docker-compose.debezium.yml up -d
```

Regenerate whenever you **add/remove a tenant** (`TENANT_IDS`) or **add a table**
to `indexer/registry/`.

## What each instance does

- Reads the tenant's MySQL binlog (`{ID}_APPLICATION_DB_*`, using the dedicated
  `{ID}_CDC_DB_USER` which needs `REPLICATION SLAVE, REPLICATION CLIENT, SELECT`).
- Emits to Redis streams `cdc_{tenant}.{db}.{table}` — exactly what the indexer
  consumer subscribes to.
- Unique `database.server.id`, its own offset + schema-history volume.
- Exposes Quarkus health on `:8080` (`/q/health/ready`) — the indexer's `/health`
  pings it so a stuck connector is visible.

## MySQL prerequisites

- `binlog_format=ROW`, `binlog_row_image=FULL`.
- **Binlog retention longer than worst-case Debezium downtime.** If binlogs are
  purged past Debezium's saved offset it gets stuck on `Error 1236` and captures
  nothing. See the recovery runbook in the top-level [README](../README.md#runbook).

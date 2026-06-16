#!/usr/bin/env python3
"""gen_debezium.py — render one Debezium Server per tenant into a compose file.

Debezium Server is single-source-per-instance, so multi-tenant CDC = one
Debezium per client. Rather than hand-maintain N near-identical services, this
generator derives everything from the SAME sources the indexer uses:

  * tenants            → indexer.tenants.all_tenants()   (db host/port/name/creds, topic prefix)
  * captured tables    → indexer.registry.TABLE_REGISTRY (the 45 indexed tables)

so Debezium's table.include.list can never drift from what the indexer indexes
— add a table to the registry and it's captured automatically on regen.

Output: docker-compose.debezium.yml  (one `debezium-<tenant>` service each).

Secrets are NOT baked in — DB/Redis creds are emitted as ${ENV} references and
resolved by `docker compose` from .env at run time. Only non-secret, static
per-tenant values (server.id, topic.prefix, db name, table list) are inlined.

Each instance:
  * unique database.server.id (required by MySQL replication)
  * its own named volume for offsets + schema history (per-tenant isolation)
  * Quarkus health on :8080 (so the indexer /health can detect a stuck connector
    — e.g. the binlog-purged "Error 1236" loop)
  * restart: unless-stopped

Usage:
    python scripts/gen_debezium.py            # writes docker-compose.debezium.yml
    docker compose -f docker-compose.yaml -f docker-compose.debezium.yml up -d
"""

from __future__ import annotations

import sys
from pathlib import Path

# Import the SAME registry + tenant sources the indexer uses.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from indexer.registry.overrides import resolve_registry  # noqa: E402
from indexer.tenants import all_tenants  # noqa: E402

DEBEZIUM_IMAGE = "debezium/server:3.0.0.Final"
_BASE_SERVER_ID = 5400  # incremented per tenant; must be unique across MySQL replicas
OUTPUT = Path(__file__).resolve().parents[1] / "docker-compose.debezium.yml"


def _env_ref(client_id: str, suffix: str) -> str:
    """Compose ${VAR} reference for a per-tenant env var (resolved from .env)."""
    return "${%s_%s}" % (client_id.upper(), suffix)


def _service(client_id: str, server_id: int) -> str:
    cid_upper = client_id.upper()
    tables = resolve_registry(client_id)  # this tenant's real table set
    table_list = ",".join(f"${{{cid_upper}_APPLICATION_DB_NAME}}.{t}" for t in tables)
    # NOTE: Debezium Server maps env vars to properties: dots→underscores, uppercased.
    return f"""
  debezium-{client_id}:
    image: {DEBEZIUM_IMAGE}
    restart: unless-stopped
    mem_limit: ${{DEBEZIUM_MEM_LIMIT:-1g}}
    mem_reservation: ${{DEBEZIUM_MEM_RESERVATION:-512m}}
    cpus: ${{DEBEZIUM_CPUS:-1}}
    environment:
      DEBEZIUM_SOURCE_CONNECTOR_CLASS: io.debezium.connector.mysql.MySqlConnector
      DEBEZIUM_SOURCE_DATABASE_HOSTNAME: {_env_ref(client_id, "APPLICATION_DB_HOST")}
      DEBEZIUM_SOURCE_DATABASE_PORT: {_env_ref(client_id, "APPLICATION_DB_PORT")}
      DEBEZIUM_SOURCE_DATABASE_USER: {_env_ref(client_id, "CDC_DB_USER")}
      DEBEZIUM_SOURCE_DATABASE_PASSWORD: {_env_ref(client_id, "CDC_DB_PASSWORD")}
      DEBEZIUM_SOURCE_DATABASE_SERVER_ID: "{server_id}"
      DEBEZIUM_SOURCE_TOPIC_PREFIX: cdc_{client_id}
      DEBEZIUM_SOURCE_DATABASE_INCLUDE_LIST: {_env_ref(client_id, "APPLICATION_DB_NAME")}
      DEBEZIUM_SOURCE_TABLE_INCLUDE_LIST: "{table_list}"
      # snapshot 'no_data' = capture schema only, no row backfill (use POST /{{client}}/sync
      # for backfill). Override to 'initial' for first-time CDC-driven backfill.
      DEBEZIUM_SOURCE_SNAPSHOT_MODE: ${{DEBEZIUM_SNAPSHOT_MODE:-no_data}}
      DEBEZIUM_SOURCE_SNAPSHOT_LOCKING_MODE: none
      DEBEZIUM_SOURCE_POLL_INTERVAL_MS: "100"
      DEBEZIUM_SOURCE_DECIMAL_HANDLING_MODE: string
      DEBEZIUM_SOURCE_TIME_PRECISION_MODE: connect
      DEBEZIUM_SOURCE_BIGINT_UNSIGNED_HANDLING_MODE: long
      DEBEZIUM_SOURCE_OFFSET_STORAGE: org.apache.kafka.connect.storage.FileOffsetBackingStore
      DEBEZIUM_SOURCE_OFFSET_STORAGE_FILE_FILENAME: /debezium/data/offsets.dat
      DEBEZIUM_SOURCE_OFFSET_FLUSH_INTERVAL_MS: "10000"
      DEBEZIUM_SOURCE_SCHEMA_HISTORY_INTERNAL: io.debezium.storage.file.history.FileSchemaHistory
      DEBEZIUM_SOURCE_SCHEMA_HISTORY_INTERNAL_FILE_FILENAME: /debezium/data/schema-history.dat
      DEBEZIUM_SOURCE_SCHEMA_HISTORY_INTERNAL_STORE_ONLY_CAPTURED_TABLES_DDL: "true"
      DEBEZIUM_FORMAT_VALUE: json
      DEBEZIUM_FORMAT_KEY: json
      DEBEZIUM_FORMAT_VALUE_SCHEMAS_ENABLE: "false"
      DEBEZIUM_FORMAT_KEY_SCHEMAS_ENABLE: "false"
      DEBEZIUM_SINK_TYPE: redis
      DEBEZIUM_SINK_REDIS_ADDRESS: ${{REDIS_HOST:-redis}}:${{REDIS_PORT:-6379}}
      DEBEZIUM_SINK_REDIS_PASSWORD: ${{REDIS_PASSWORD}}
      DEBEZIUM_SINK_REDIS_NULL_VALUE: default
      # Quarkus health (liveness/readiness reflects connector state → catches the
      # binlog-purged "Error 1236" stuck loop).
      QUARKUS_HTTP_PORT: "8080"
      QUARKUS_HTTP_HOST: 0.0.0.0
    volumes:
      - debezium_{client_id}_data:/debezium/data
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://localhost:8080/q/health/ready || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 40s
    networks:
      - default
"""


def main() -> None:
    tenants = all_tenants()
    services = "".join(
        _service(t.client_id, _BASE_SERVER_ID + i) for i, t in enumerate(tenants)
    )
    volumes = "".join(f"  debezium_{t.client_id}_data:\n" for t in tenants)

    header = (
        "# GENERATED by scripts/gen_debezium.py — DO NOT EDIT BY HAND.\n"
        "# One Debezium Server per tenant (derived from TENANT_IDS + the indexer registry).\n"
        "# Regenerate after changing tenants or the table registry:\n"
        "#   python scripts/gen_debezium.py\n"
        "# Run alongside the indexer:\n"
        "#   docker compose -f docker-compose.yaml -f docker-compose.debezium.yml up -d\n\n"
        "services:\n"
    )
    footer = (
        "\nvolumes:\n" + volumes +
        "\nnetworks:\n"
        "  default:\n"
        "    name: ${INFRA_NETWORK:-cdc_default}\n"
        "    external: ${INFRA_NETWORK_EXTERNAL:-false}\n"
    )

    OUTPUT.write_text(header + services + footer, encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    print(f"  tenants: {[t.client_id for t in tenants]}")
    for t in tenants:
        print(f"  {t.client_id}: {len(resolve_registry(t.client_id))} tables")
    print(f"  server.id range: {_BASE_SERVER_ID}..{_BASE_SERVER_ID + len(tenants) - 1}")


if __name__ == "__main__":
    main()

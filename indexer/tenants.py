"""tenants.py — multi-tenant client registry.

One entry point for everything tenant-related. Clients are declared in the
TENANT_IDS env var (comma-separated, e.g. "spar,acme") and configured via
per-client env vars:

    {ID}_APPLICATION_DB_HOST          (default: localhost)
    {ID}_APPLICATION_DB_PORT          (default: 3306)
    {ID}_APPLICATION_DB_NAME          (required)
    {ID}_APPLICATION_DB_USER          (required)
    {ID}_APPLICATION_DB_PASSWORD      (required)
    {ID}_APPLICATION_DB_POOL_SIZE     (default: 3)
    {ID}_APPLICATION_DB_MAX_OVERFLOW  (default: 7)
    {ID}_CDC_TOPIC_PREFIX             (default: cdc_{id})

where {ID} is the client_id uppercased (client "spar" → SPAR_APPLICATION_DB_HOST).

Adding a client:    add env vars + append to TENANT_IDS + restart.
Removing a client:  drop from TENANT_IDS + restart (their data stays until
                    manually deleted — removal is reversible).

The registry fails fast: a client listed in TENANT_IDS with missing required
vars raises at import time, so a half-configured tenant can never serve traffic.

Tenants sharing a physical (db_host, db_port) share ONE Debezium Server
instance (one connector = one binlog stream), so they MUST also share the
same CDC_TOPIC_PREFIX — enforced here at load time. See debezium_host_groups().

Public API:
    get_tenant(client_id) -> TenantConfig      raises UnknownTenantError
    all_tenants()         -> list[TenantConfig]
    get_tenant_by_topic_prefix(prefix) -> TenantConfig | None
    debezium_group_id(db_host, db_port) -> str          stable id for a host's Debezium instance
    debezium_host_groups() -> dict[str, list[TenantConfig]]   tenants grouped by Debezium instance
    CLIENT_ID_RE                               validation regex (shared with routes)
    TENANT_CLAIM_STRICT                        reject JWTs without client_id claim
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass

from dotenv import load_dotenv
from sqlalchemy.engine import URL

load_dotenv()

CLIENT_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")

# When true (default), JWTs without a client_id claim are rejected. Secure by
# default: a deployment that forgets to configure this is locked down, not open.
# Set TENANT_CLAIM_STRICT=false ONLY for local testing with tokens that don't
# carry the claim yet.
TENANT_CLAIM_STRICT: bool = os.environ.get("TENANT_CLAIM_STRICT", "true").lower() in ("1", "true", "yes")


class UnknownTenantError(KeyError):
    """Raised when a client_id is not in the registry."""


class TenantConfigError(ValueError):
    """Raised at load time when a tenant's configuration is invalid."""


@dataclass(frozen=True)
class TenantConfig:
    client_id: str
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    pool_size: int
    max_overflow: int
    cdc_topic_prefix: str

    @property
    def db_url(self) -> URL:
        return URL.create(
            drivername="mysql+pymysql",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )

    def index_for(self, module: str) -> str:
        """OpenSearch index name for one of this client's modules."""
        return f"{self.client_id}_{module}"


def _env(client_id: str, suffix: str, default: str | None = None) -> str:
    """Read {CLIENT_ID}_{suffix} from the environment."""
    key = f"{client_id.upper()}_{suffix}"
    val = os.environ.get(key, default)
    if val is None:
        raise TenantConfigError(
            f"Tenant '{client_id}' is listed in TENANT_IDS but required env var {key} is missing."
        )
    return val


def _load_tenant(client_id: str) -> TenantConfig:
    if not CLIENT_ID_RE.match(client_id):
        raise TenantConfigError(
            f"Invalid client_id {client_id!r} in TENANT_IDS — must match {CLIENT_ID_RE.pattern}"
        )

    db_name = _env(client_id, "APPLICATION_DB_NAME")
    topic_prefix = _env(client_id, "CDC_TOPIC_PREFIX", f"cdc_{client_id}")

    # Dots would break "prefix.db.table" CDC stream-key parsing
    for label, value in (("db name", db_name), ("CDC topic prefix", topic_prefix)):
        if "." in value:
            raise TenantConfigError(
                f"Tenant '{client_id}' {label} {value!r} must not contain '.'"
            )

    return TenantConfig(
        client_id=client_id,
        db_host=_env(client_id, "APPLICATION_DB_HOST", "localhost"),
        db_port=int(_env(client_id, "APPLICATION_DB_PORT", "3306")),
        db_name=db_name,
        db_user=_env(client_id, "APPLICATION_DB_USER"),
        db_password=_env(client_id, "APPLICATION_DB_PASSWORD"),
        pool_size=int(_env(client_id, "APPLICATION_DB_POOL_SIZE", "3")),
        max_overflow=int(_env(client_id, "APPLICATION_DB_MAX_OVERFLOW", "7")),
        cdc_topic_prefix=topic_prefix,
    )


def _load_tenants() -> dict[str, TenantConfig]:
    raw = os.environ.get("TENANT_IDS", "")
    ids = [t.strip().lower() for t in raw.split(",") if t.strip()]
    if not ids:
        raise TenantConfigError(
            "TENANT_IDS is empty — declare at least one client, e.g. TENANT_IDS=spar"
        )

    tenants: dict[str, TenantConfig] = {}
    seen_routing: dict[tuple[str, str], str] = {}  # (topic_prefix, db_name) -> client_id

    for client_id in ids:
        if client_id in tenants:
            raise TenantConfigError(f"Duplicate client_id {client_id!r} in TENANT_IDS")
        cfg = _load_tenant(client_id)
        routing_key = (cfg.cdc_topic_prefix, cfg.db_name)
        if routing_key in seen_routing:
            raise TenantConfigError(
                f"Tenants '{seen_routing[routing_key]}' and '{client_id}' share CDC routing key "
                f"{routing_key} — set distinct {client_id.upper()}_CDC_TOPIC_PREFIX values."
            )
        seen_routing[routing_key] = client_id
        tenants[client_id] = cfg

    # Debezium reads one MySQL server's binlog per connector instance, so
    # tenants sharing a physical (db_host, db_port) share ONE Debezium Server
    # container (see debezium_host_groups()) instead of one each. That container
    # has exactly one topic.prefix, so every tenant on the same host must agree
    # on cdc_topic_prefix — otherwise CDC stream routing would be ambiguous.
    prefix_by_host: dict[tuple[str, int], tuple[str, str]] = {}
    for cfg in tenants.values():
        host_key = (cfg.db_host, cfg.db_port)
        if host_key not in prefix_by_host:
            prefix_by_host[host_key] = (cfg.cdc_topic_prefix, cfg.client_id)
            continue
        existing_prefix, existing_client = prefix_by_host[host_key]
        if existing_prefix != cfg.cdc_topic_prefix:
            raise TenantConfigError(
                f"Tenants '{existing_client}' and '{cfg.client_id}' share DB host "
                f"{cfg.db_host}:{cfg.db_port} but have different CDC topic prefixes "
                f"({existing_prefix!r} vs {cfg.cdc_topic_prefix!r}). Tenants on the same "
                f"physical host share one Debezium instance and must use the same "
                f"CDC_TOPIC_PREFIX value."
            )

    return tenants


# Lazy singleton — loaded on first access so importing this module never crashes;
# main.py lifespan calls all_tenants() at boot to fail fast on bad config.
_tenants: dict[str, TenantConfig] | None = None


def _registry() -> dict[str, TenantConfig]:
    global _tenants
    if _tenants is None:
        _tenants = _load_tenants()
    return _tenants


def get_tenant(client_id: str) -> TenantConfig:
    """Return the TenantConfig for client_id. Raises UnknownTenantError."""
    try:
        return _registry()[client_id]
    except KeyError:
        raise UnknownTenantError(client_id) from None


def all_tenants() -> list[TenantConfig]:
    return list(_registry().values())


def get_tenant_by_topic_prefix(prefix: str) -> TenantConfig | None:
    for cfg in _registry().values():
        if cfg.cdc_topic_prefix == prefix:
            return cfg
    return None


def debezium_group_id(db_host: str, db_port: int) -> str:
    """Stable id for the Debezium instance covering (db_host, db_port).

    Debezium reads one MySQL server's binlog per connector instance, so
    tenants sharing a physical host share one Debezium Server container named
    from this id. Used for both container/volume naming (gen_debezium.py) and
    health-check URLs (indexer/api.py) — they must derive the identical id
    from the same (db_host, db_port), or the health check probes a container
    that doesn't exist.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", db_host.lower()).strip("_")
    # An IP-address host (e.g. "13.232.229.242") slugifies to a leading digit,
    # which Docker Compose's ${VAR} interpolation can't reference (env var
    # names must start with a letter or underscore) — prefix it so the
    # derived {GROUP_ID}_CDC_DB_USER/PASSWORD names stay valid.
    if not slug or slug[0].isdigit():
        slug = f"host_{slug}"
    return f"{slug}_{db_port}"


def debezium_host_groups() -> dict[str, list[TenantConfig]]:
    """All tenants grouped by the Debezium instance that serves their DB host.

    Key is the same id debezium_group_id() would produce for that group's
    (db_host, db_port) — one Debezium Server container per group, not per tenant.
    """
    groups: dict[str, list[TenantConfig]] = defaultdict(list)
    for cfg in all_tenants():
        groups[debezium_group_id(cfg.db_host, cfg.db_port)].append(cfg)
    return dict(groups)

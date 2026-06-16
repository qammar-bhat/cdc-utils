"""Tenant-aware registry resolution.

The base registry (`TABLE_REGISTRY`) defines every table once — the ~90% that's
identical across tenants. Each tenant's genuine schema deltas live in its own
module, `indexer/registry/tenants/<client_id>.py`, as an `OVERRIDES` dict.

`resolve_registry(client_id)` = base registry with that tenant's overrides
merged on. Override grammar:

  {"table": {"sql": "..."}}   shallow-merge — replace ONLY the given keys,
                              inherit the rest (doc builders, strategy, …).
  {"table": None}             this tenant does NOT have the table → drop it.
  {"new_table": {full cfg}}   a table only this tenant has (give it a "module"
                              so doc_types can map it).
"""

from __future__ import annotations

import importlib
from functools import lru_cache

import logfire

from indexer.registry import TABLE_REGISTRY


def apply_overrides(base: dict[str, dict], overrides: dict[str, dict | None]) -> dict[str, dict]:
    """Pure merge of an overrides dict onto a base registry. Does not mutate base."""
    reg = dict(base)
    for table, override in overrides.items():
        if override is None:
            reg.pop(table, None)                      # tenant lacks this table
        elif table in reg:
            reg[table] = {**reg[table], **override}   # merge: change only given keys
        else:
            reg[table] = override                     # table unique to this tenant
    return reg


def _load_tenant_overrides(client_id: str) -> dict[str, dict | None]:
    """Load OVERRIDES from indexer/registry/tenants/<client_id>.py ({} if absent)."""
    try:
        mod = importlib.import_module(f"indexer.registry.tenants.{client_id}")
    except ModuleNotFoundError:
        return {}
    overrides = getattr(mod, "OVERRIDES", None)
    if not isinstance(overrides, dict):
        logfire.warning("tenant override module has no OVERRIDES dict", client_id=client_id)
        return {}
    return overrides


@lru_cache(maxsize=None)
def resolve_registry(client_id: str) -> dict[str, dict]:
    """Return the base registry with `client_id`'s overrides applied.

    Cached per client_id (registry is static at runtime). Callers must treat the
    result as read-only — it is shared across calls.
    """
    overrides = _load_tenant_overrides(client_id)
    reg = apply_overrides(TABLE_REGISTRY, overrides)

    # Startup-visible audit: log what each tenant changed, and flag suspicious
    # entries (a partial override onto a table that doesn't exist in the base is
    # almost always a typo'd table name).
    if overrides:
        applied, dropped, added = [], [], []
        for table, ov in overrides.items():
            if ov is None:
                dropped.append(table)
            elif table in TABLE_REGISTRY:
                applied.append(table)
            else:
                added.append(table)
                if "sql" not in ov:
                    logfire.warning(
                        "tenant override targets unknown base table and is not a full cfg "
                        "(typo'd table name?)",
                        client_id=client_id, table=table,
                    )
        logfire.info(
            "tenant registry resolved",
            client_id=client_id, overridden=applied, dropped=dropped, added=added,
            table_count=len(reg),
        )
    return reg

"""Tenant-aware registry resolution (base + per-tenant override modules)."""
from __future__ import annotations

from indexer.registry import TABLE_REGISTRY
from indexer.registry.overrides import apply_overrides, resolve_registry


# ── pure merge semantics (apply_overrides) ────────────────────────────────────

def test_empty_overrides_returns_base():
    reg = apply_overrides(TABLE_REGISTRY, {})
    assert set(reg) == set(TABLE_REGISTRY)


def test_merge_replaces_only_given_keys():
    base = {"t": {"sql": "OLD", "module": "account", "build_title": object()}}
    reg = apply_overrides(base, {"t": {"sql": "NEW"}})
    assert reg["t"]["sql"] == "NEW"
    assert reg["t"]["module"] == "account"            # inherited
    assert reg["t"]["build_title"] is base["t"]["build_title"]


def test_none_drops_table():
    base = {"a": {"sql": "x"}, "b": {"sql": "y"}}
    reg = apply_overrides(base, {"a": None})
    assert "a" not in reg and "b" in reg


def test_new_table_added():
    base = {"a": {"sql": "x"}}
    reg = apply_overrides(base, {"only_here": {"module": "account", "sql": "SELECT 1"}})
    assert reg["only_here"]["sql"] == "SELECT 1"


def test_base_not_mutated():
    base = {"t": {"sql": "OLD"}}
    apply_overrides(base, {"t": {"sql": "NEW"}, "z": None})
    assert base["t"]["sql"] == "OLD"


# ── real per-tenant modules (resolve_registry) ────────────────────────────────

def test_dev_env_uses_base_unchanged():
    assert set(resolve_registry("dev_env")) == set(TABLE_REGISTRY)


def test_unknown_tenant_falls_back_to_base():
    # no tenants/<id>.py module → empty overrides → base
    assert set(resolve_registry("no_such_tenant")) == set(TABLE_REGISTRY)


def test_spar_opportunity_override_applied():
    merged = resolve_registry("spar")["sl_opportunity_parties"]
    base = TABLE_REGISTRY["sl_opportunity_parties"]
    assert "op.company_id" not in merged["sql"]
    assert "p.company_id AS company_id" in merged["sql"]
    # untouched keys inherited from base
    assert merged["module"] == base["module"]
    assert merged["build_title"] is base["build_title"]


def test_resolve_does_not_mutate_base():
    resolve_registry("spar")
    assert "op.company_id" in TABLE_REGISTRY["sl_opportunity_parties"]["sql"]

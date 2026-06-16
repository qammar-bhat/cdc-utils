"""Tenant registry edge cases (multi-tenant config contract)."""
from __future__ import annotations

import pytest

from indexer.tenants import (
    CLIENT_ID_RE,
    TenantConfigError,
    UnknownTenantError,
    all_tenants,
    get_tenant,
    get_tenant_by_topic_prefix,
    _load_tenants,
)


def test_known_tenants_load():
    ids = {t.client_id for t in all_tenants()}
    assert {"spar", "dev_env"} <= ids


def test_unknown_tenant_raises():
    with pytest.raises(UnknownTenantError):
        get_tenant("nope")


def test_db_url_built_from_config():
    t = get_tenant("spar")
    url = t.db_url
    assert url.drivername == "mysql+pymysql"
    assert url.database == "shared_db"


def test_index_for_naming():
    t = get_tenant("spar")
    assert t.index_for("account") == "spar_account"


def test_topic_prefix_lookup():
    t = get_tenant_by_topic_prefix("cdc_dev_env")
    assert t is not None and t.client_id == "dev_env"
    assert get_tenant_by_topic_prefix("cdc_missing") is None


def test_client_id_regex():
    assert CLIENT_ID_RE.match("spar")
    assert not CLIENT_ID_RE.match("Spar")     # uppercase rejected
    assert not CLIENT_ID_RE.match("1spar")    # must start with a letter


def test_empty_tenant_ids_raises(monkeypatch):
    monkeypatch.setenv("TENANT_IDS", "")
    with pytest.raises(TenantConfigError):
        _load_tenants()


def test_missing_required_var_raises(monkeypatch):
    monkeypatch.setenv("TENANT_IDS", "acme")
    monkeypatch.delenv("ACME_APPLICATION_DB_NAME", raising=False)
    with pytest.raises(TenantConfigError):
        _load_tenants()


def test_routing_collision_raises(monkeypatch):
    """Two tenants with the SAME topic prefix AND db name is a fatal collision."""
    monkeypatch.setenv("TENANT_IDS", "a,b")
    for cid in ("A", "B"):
        monkeypatch.setenv(f"{cid}_APPLICATION_DB_NAME", "same_db")
        monkeypatch.setenv(f"{cid}_APPLICATION_DB_USER", "u")
        monkeypatch.setenv(f"{cid}_APPLICATION_DB_PASSWORD", "p")
        monkeypatch.setenv(f"{cid}_CDC_TOPIC_PREFIX", "cdc_same")
    with pytest.raises(TenantConfigError):
        _load_tenants()

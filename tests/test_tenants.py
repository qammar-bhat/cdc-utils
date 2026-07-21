"""Tenant registry edge cases (multi-tenant config contract)."""
from __future__ import annotations

import pytest

from indexer.tenants import (
    CLIENT_ID_RE,
    TenantConfigError,
    UnknownTenantError,
    all_tenants,
    debezium_group_id,
    debezium_host_groups,
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


def test_debezium_group_id_is_stable_and_slugified():
    assert debezium_group_id("mysql", 3306) == "mysql_3306"
    assert debezium_group_id("My-Host.internal", 3307) == "my_host_internal_3307"


def test_debezium_group_id_handles_ip_host():
    """An IP host must not produce a digit-leading id — ${VAR} interpolation
    in docker-compose requires env var names to start with a letter/underscore."""
    gid = debezium_group_id("13.232.229.242", 3306)
    assert not gid[0].isdigit()
    assert gid == "host_13_232_229_242_3306"


def test_host_sharing_tenants_grouped_together(monkeypatch):
    """Tenants on the same (db_host, db_port) share one Debezium instance."""
    monkeypatch.setenv("TENANT_IDS", "aa,bb")
    for cid, db_name in (("AA", "a_db"), ("BB", "b_db")):
        monkeypatch.setenv(f"{cid}_APPLICATION_DB_HOST", "shared-mysql")
        monkeypatch.setenv(f"{cid}_APPLICATION_DB_NAME", db_name)
        monkeypatch.setenv(f"{cid}_APPLICATION_DB_USER", "u")
        monkeypatch.setenv(f"{cid}_APPLICATION_DB_PASSWORD", "p")
        monkeypatch.setenv(f"{cid}_CDC_TOPIC_PREFIX", "cdc_shared")  # must match across the group
    import indexer.tenants as t
    t._tenants = None
    groups = debezium_host_groups()
    gid = debezium_group_id("shared-mysql", 3306)
    assert {cfg.client_id for cfg in groups[gid]} == {"aa", "bb"}


def test_host_sharing_tenants_require_same_topic_prefix(monkeypatch):
    """A connector has one topic.prefix, so co-located tenants can't diverge."""
    monkeypatch.setenv("TENANT_IDS", "aa,bb")
    for cid, db_name, prefix in (("AA", "a_db", "cdc_aa"), ("BB", "b_db", "cdc_bb")):
        monkeypatch.setenv(f"{cid}_APPLICATION_DB_HOST", "shared-mysql")
        monkeypatch.setenv(f"{cid}_APPLICATION_DB_NAME", db_name)
        monkeypatch.setenv(f"{cid}_APPLICATION_DB_USER", "u")
        monkeypatch.setenv(f"{cid}_APPLICATION_DB_PASSWORD", "p")
        monkeypatch.setenv(f"{cid}_CDC_TOPIC_PREFIX", prefix)
    with pytest.raises(TenantConfigError):
        _load_tenants()

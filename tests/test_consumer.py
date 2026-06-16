"""Unit tests for CDC consumer pure functions (ported from the hub).

Multi-tenant: _parse_messages stamps every event with the tenant the stream
belongs to (consumer knows it from the stream key → client_id map).
"""
from __future__ import annotations

import json

from indexer.consumer import _MAX_RETRIES, _build_stream_map, _parse_messages

_CLIENT = "spar"


# ── _parse_messages ──────────────────────────────────────────────────────────

def test_parse_messages_skips_empty_data():
    events, ids = _parse_messages([("1234-0", {"data": ""})], _CLIENT)
    assert events == []
    assert ids == ["1234-0"]   # still ACK'd


def test_parse_messages_skips_missing_data():
    events, ids = _parse_messages([("1234-0", {})], _CLIENT)
    assert events == []
    assert ids == ["1234-0"]


def test_parse_messages_extracts_insert_event():
    payload = json.dumps({
        "before": None,
        "after": {"id": 42, "asset_name": "Pump"},
        "source": {"table": "assets", "db": "spar_erpforce"},
        "op": "c",
    })
    events, ids = _parse_messages([("1234-0", {"data": payload})], _CLIENT)
    assert len(events) == 1
    assert events[0]["source"]["table"] == "assets"
    assert events[0]["op"] == "c"
    assert events[0]["after"]["id"] == 42
    assert ids == ["1234-0"]


def test_parse_messages_stamps_client_id():
    payload = json.dumps({"after": {"id": 1}, "source": {"table": "assets"}, "op": "c"})
    events, _ = _parse_messages([("1-0", {"data": payload})], "dev_env")
    assert events[0]["client_id"] == "dev_env"


def test_parse_messages_handles_debezium_payload_wrapper():
    payload = json.dumps({"payload": {
        "before": None, "after": {"id": 1}, "source": {"table": "assets"}, "op": "c",
    }})
    events, _ = _parse_messages([("1234-0", {"data": payload})], _CLIENT)
    assert events[0]["source"]["table"] == "assets"


def test_parse_messages_skips_event_with_no_table():
    payload = json.dumps({"ddl": "CREATE TABLE x", "source": {}})
    events, ids = _parse_messages([("1234-0", {"data": payload})], _CLIENT)
    assert events == []
    assert ids == ["1234-0"]


def test_parse_messages_handles_batch():
    def _make(table, row_id):
        data = json.dumps({"after": {"id": row_id}, "source": {"table": table}, "op": "c"})
        return (f"{row_id}-0", {"data": data})

    messages = [_make("assets", 1), _make("assets", 2), ("3-0", {"data": ""})]
    events, ids = _parse_messages(messages, _CLIENT)
    assert len(events) == 2
    assert len(ids) == 3
    assert all(e["client_id"] == _CLIENT for e in events)


# ── dead-letter threshold ─────────────────────────────────────────────────────

def test_max_retries_constant():
    assert _MAX_RETRIES == 5


def test_dead_letter_threshold_filters_correctly():
    pending = [
        {"message_id": "a", "times_delivered": 5},   # DLQ
        {"message_id": "b", "times_delivered": 4},   # live
        {"message_id": "c", "times_delivered": 6},   # DLQ
        {"message_id": "d", "times_delivered": 1},   # live
    ]
    dlq = [p["message_id"] for p in pending if p["times_delivered"] >= _MAX_RETRIES]
    live = [p["message_id"] for p in pending if p["times_delivered"] < _MAX_RETRIES]
    assert dlq == ["a", "c"]
    assert live == ["b", "d"]


# ── stream map (multi-tenant routing) ─────────────────────────────────────────

def test_build_stream_map_covers_every_tenant_x_table():
    """Stream key {prefix}.{db}.{table} → client_id, for all tenants × tables."""
    from indexer.registry import TABLE_REGISTRY
    from indexer.tenants import all_tenants

    stream_map = _build_stream_map()
    tenants = all_tenants()
    assert len(stream_map) == len(tenants) * len(TABLE_REGISTRY)

    for t in tenants:
        key = f"{t.cdc_topic_prefix}.{t.db_name}.parties"
        assert stream_map[key] == t.client_id


def test_build_stream_map_disambiguates_same_db_name_by_prefix():
    """spar and dev_env share a db name; the topic prefix keeps them distinct."""
    stream_map = _build_stream_map()
    assert stream_map["cdc_spar.shared_db.parties"] == "spar"
    assert stream_map["cdc_dev_env.shared_db.parties"] == "dev_env"

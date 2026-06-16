"""CDC event handler — called by the Redis Streams consumer for each MySQL change event.

Multi-tenant: every event carries a "client_id" (stamped by the consumer from
the stream it arrived on). Row refetches run against that client's database and
documents land in that client's indices ({client_id}_{module}).
"""
from __future__ import annotations

import asyncio
import re
from collections import defaultdict

import logfire

from indexer.os_client import get_opensearch_client
from indexer.doc_types import index_for
from indexer.embedder import embedder
from indexer.indexing import _build_doc_id, _normalise_date
from indexer.registry.overrides import resolve_registry
from indexer.db import execute_safe_query

# SQL words that can directly follow "FROM <table>" but are NOT a table alias.
# Without this guard, `FROM journal_entries WHERE ...` would capture "WHERE" as
# the alias and build `... AND WHERE.id = :row_id` (broken). Tables written with
# a real alias (`FROM purchase_invoices pi`) still resolve correctly.
_SQL_NON_ALIAS = frozenset({
    "WHERE", "LEFT", "RIGHT", "INNER", "OUTER", "FULL", "CROSS", "JOIN",
    "GROUP", "ORDER", "LIMIT", "HAVING", "ON", "AS", "UNION", "WINDOW",
})


def _id_column_for(table: str, base_sql: str) -> str:
    """Return the id column to filter the CDC row refetch by.

    Uses the table's alias if the registry SQL declares one (`FROM t alias ...`),
    else the bare `id`. Guards against capturing a SQL keyword as an alias when
    the table has no alias (`FROM t WHERE ...`).
    """
    m = re.search(rf"\bFROM\s+{re.escape(table)}\s+(\w+)", base_sql, re.IGNORECASE)
    if m and m.group(1).upper() not in _SQL_NON_ALIAS:
        return f"{m.group(1)}.id"
    return "id"


async def ingest_change_events_batch(events: list[dict]) -> None:
    """Process a batch of CDC events — one embedding call + one bulk upsert per index."""
    try:
        await _ingest_change_events_batch(events)
    except Exception:
        logfire.exception("indexer CDC batch failed", event_count=len(events))
        raise


async def _ingest_change_events_batch(events: list[dict]) -> None:
    deletes = [e for e in events if e.get("op") == "d"]
    upserts = [e for e in events if e.get("op") != "d"]

    # deletes are fast — no embedding needed
    for event in deletes:
        table = event["source"]["table"]
        client_id = event["client_id"]
        cfg = resolve_registry(client_id).get(table)
        if cfg is None:
            continue
        row_id = event["before"]["id"]
        await _delete_from_index(table, index_for(client_id, cfg["module"]), row_id)
        logfire.info("indexer CDC delete", table=table, client_id=client_id, source_id=row_id)

    if not upserts:
        return

    # build (client_id, table, cfg, row_id) list — skip unknowns
    targets = []
    for event in upserts:
        table = event["source"]["table"]
        client_id = event["client_id"]
        cfg = resolve_registry(client_id).get(table)
        if cfg is None:
            logfire.warning("indexer CDC: unknown table, skipping", table=table)
            continue
        row_id = (event.get("after") or {}).get("id")
        if row_id is None:
            logfire.warning("indexer CDC: no id in after payload", table=table)
            continue
        targets.append((client_id, table, cfg, row_id))

    if not targets:
        return

    # fetch all rows concurrently (each against its client's database)
    # junction-strategy tables (e.g. items × item_companies) return one row per company
    row_lists = await asyncio.gather(
        *[_fetch_rows(client_id, table, cfg, row_id) for client_id, table, cfg, row_id in targets],
        return_exceptions=True,
    )

    valid = []
    for (client_id, table, cfg, row_id), row_list in zip(targets, row_lists):
        if isinstance(row_list, BaseException):
            logfire.error(
                "indexer CDC: _fetch_rows raised",
                table=table,
                client_id=client_id,
                source_id=row_id,
                error=str(row_list),
            )
        elif not row_list:
            # Row missing from filtered query — soft-deleted. Remove from index.
            await _delete_from_index(table, index_for(client_id, cfg["module"]), row_id)
            logfire.info("indexer CDC soft-delete", table=table, client_id=client_id, source_id=row_id)
        else:
            for row in row_list:
                valid.append((client_id, table, cfg, row))

    if not valid:
        return

    # single embed_many call for the whole batch — embed title + text_content together
    titles = [cfg["build_title"](row) for _, _, cfg, row in valid]
    texts = [cfg["build_text_content"](row) for _, _, cfg, row in valid]
    embed_inputs = [f"{t} {x}".strip() if t else x for t, x in zip(titles, texts)]
    logfire.info("indexer CDC embedding batch", count=len(embed_inputs))
    embeddings = await embedder.embed_many(embed_inputs)

    # group docs by (tenant) index for bulk upsert — one batch can mix tenants
    by_index: dict[str, list] = defaultdict(list)
    for (client_id, table, cfg, row), title, text, embedding in zip(valid, titles, texts, embeddings):
        strategy = cfg["company_id_strategy"]
        doc_id = _build_doc_id(table, row, strategy)
        company_id = row.get("company_id")
        get_amount = cfg.get("get_amount", lambda r: None)
        raw_amount = get_amount(row)
        doc = {
            "id":               doc_id,
            "source_id":        row["id"],
            "doc_type":         table,
            "module":           cfg["module"],
            "company_id":       str(company_id) if company_id is not None else "0",
            "title":            title,
            "reference":        cfg["get_reference"](row),
            "status":           cfg["get_status"](row),
            "date":             _normalise_date(cfg["get_date"](row)),
            "amount":           float(raw_amount) if raw_amount is not None else None,
            "text_content":     text,
            "embedding":        embedding,
            "party_name":       row.get("customer_name") or row.get("vendor_name") or row.get("party_name") or row.get("employee_name"),
            "approval_status":  row.get("approval_status"),
            "transaction_type": row.get("transaction_type"),
            "email":            row.get("email"),
            "phone":            row.get("phone") or row.get("contact_no"),
        }
        by_index[index_for(client_id, cfg["module"])].append((doc_id, doc))

    loop = asyncio.get_running_loop()
    client = get_opensearch_client()
    for index, docs in by_index.items():
        bulk_body: list = []
        for doc_id, doc in docs:
            bulk_body.append({"index": {"_index": index, "_id": doc_id}})
            bulk_body.append(doc)
        resp = await loop.run_in_executor(None, lambda b=bulk_body: client.bulk(body=b))
        if resp.get("errors"):
            failed = [item for item in resp.get("items", []) if item.get("index", {}).get("error")]
            logfire.error(
                "indexer CDC bulk had errors",
                index=index,
                failed_count=len(failed),
                sample=failed[:3],
            )
            raise RuntimeError(f"OpenSearch bulk failed for index {index}: {len(failed)} errors")

    logfire.info("indexer CDC batch upsert", count=len(valid))


async def _fetch_rows(client_id: str, table: str, cfg: dict, row_id: int) -> list[dict]:
    """Fetch all rows for a given source id from the client's database.

    Junction-strategy tables (e.g. items × item_companies) produce one row per company,
    so we return the full list rather than just the first row.

    We extract the primary table alias from the SQL (e.g. ``pi`` from
    ``FROM purchase_invoices pi``) to qualify the ``id`` column and avoid
    ambiguity in JOINed queries.
    """
    base_sql = cfg["sql"].strip().rstrip(";")
    id_col = _id_column_for(table, base_sql)

    if "WHERE" in base_sql.upper():
        sql = f"{base_sql} AND {id_col} = :row_id"
    else:
        sql = f"{base_sql} WHERE {id_col} = :row_id"
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, lambda: execute_safe_query(sql, {"row_id": row_id}, client_id=client_id)
    )


async def _delete_from_index(table: str, index: str, row_id: int) -> None:
    """Delete all OpenSearch documents for a given source row (handles junction tables)."""
    body = {"query": {"bool": {"filter": [
        {"term": {"doc_type": table}},
        {"term": {"source_id": row_id}},
    ]}}}
    loop = asyncio.get_running_loop()
    client = get_opensearch_client()
    await loop.run_in_executor(
        None,
        lambda: client.delete_by_query(index=index, body=body, conflicts="proceed"),
    )

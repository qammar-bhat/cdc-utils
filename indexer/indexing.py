"""IndexerService — reads MySQL source data and bulk-upserts into OpenSearch."""
from __future__ import annotations

import asyncio
import json
import time
from datetime import date, datetime, timezone
from typing import Any

import logfire

from indexer.config import settings
from indexer.db import execute_safe_query
from indexer.os_client import get_opensearch_client
from indexer.doc_types import index_for, indices_for
from indexer.embedder import embedder
from indexer.registry.overrides import resolve_registry

_BATCH_SIZE = 50
_JOB_TTL = 3600  # seconds — job status kept in Redis for 1 hour


async def _write_job_status(job_id: str, payload: dict) -> None:
    """Write sync job progress to Redis. Silently ignores errors."""
    try:
        from indexer.config import get_redis
        redis = get_redis()
        await redis.set(f"sync_job:{job_id}", json.dumps(payload), ex=_JOB_TTL)
    except Exception as exc:
        logfire.warning("Failed to write sync job status", job_id=job_id, error=str(exc))


def _to_float(val: Any) -> float | None:
    """Safely coerce any value to float; returns None on failure."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _to_str(val: Any) -> str | None:
    """Convert non-None value to string."""
    return str(val) if val is not None else None


_PIPELINE_NAME = "smart_search_hybrid"

_ERP_SYNONYMS = [
    "po, purchase order",
    "so, sales order",
    "do, delivery order",
    "grn, goods receipt, goods received note",
    "rfq, request for quotation, request for quote",
    "bom, bill of materials",
    "je, journal entry",
    "cn, credit note",
    "dn, debit note",
    "vra, vendor return",
    "inv, invoice",
]


def _index_mapping() -> dict:
    dimension = settings.resolve_embedding_runtime().get("dimension", 768)
    return {
        "settings": {
            "index.knn": True,
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "analysis": {
                "filter": {
                    "erp_synonyms": {
                        "type": "synonym",
                        "synonyms": _ERP_SYNONYMS,
                    },
                    "english_stop": {
                        "type": "stop",
                        "stopwords": "_english_",
                    },
                    "english_stemmer": {
                        "type": "stemmer",
                        "language": "english",
                    },
                },
                "analyzer": {
                    "erp_text": {
                        "tokenizer": "standard",
                        "filter": [
                            "lowercase",
                            "erp_synonyms",
                            "english_stop",
                            "english_stemmer",
                        ],
                    },
                },
            },
        },
        "mappings": {
            "properties": {
                # --- Core structural fields ---
                "id":           {"type": "keyword"},
                "source_id":    {"type": "long"},
                "doc_type":     {"type": "keyword"},
                "module":       {"type": "keyword"},
                "company_id":   {"type": "keyword"},
                "title": {
                    "type": "text",
                    "analyzer": "erp_text",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "reference": {
                    "type": "keyword",
                    "fields": {"text": {"type": "text", "analyzer": "erp_text"}},
                },
                "status":       {"type": "keyword"},
                "date":         {"type": "date"},
                "amount":       {"type": "double"},
                "text_content": {"type": "text", "analyzer": "erp_text"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": dimension,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "nmslib",
                    },
                },
                "party_name": {
                    "type": "text",
                    "analyzer": "standard",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "company_name": {
                    "type": "text",
                    "analyzer": "standard",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "first_name":       {"type": "keyword"},
                "last_name":        {"type": "keyword"},
                "approval_status":  {"type": "keyword"},
                "transaction_type": {"type": "keyword"},
                "email":            {"type": "keyword"},
                "phone":            {"type": "keyword"},

                # --- Invoice / payment ---
                "payment_status":          {"type": "keyword"},
                "due_date":                {"type": "date"},
                "amount_paid":             {"type": "double"},
                "amount_due":              {"type": "double"},
                "supplier_invoice_number": {"type": "keyword"},
                "order_type":              {"type": "keyword"},
                "payment_type":            {"type": "keyword"},
                "payment_method_type":     {"type": "keyword"},
                "cheque_number":           {"type": "keyword"},
                "cheque_date":             {"type": "date"},
                "is_reconciled":           {"type": "keyword"},
                "narration":               {"type": "text", "analyzer": "english"},
                "ref_type":                {"type": "keyword"},
                "party_role":              {"type": "keyword"},
                "version":                 {"type": "keyword"},
                "po_number":               {"type": "keyword"},

                # --- Party / company profile ---
                "party_type":        {"type": "keyword"},
                "vat_number":        {"type": "keyword"},
                "crn":               {"type": "keyword"},
                "sales_lead_status": {"type": "keyword"},
                "sales_op_stage":    {"type": "keyword"},
                "credit_hold":       {"type": "keyword"},
                "is_active":         {"type": "keyword"},
                "address":           {"type": "text", "analyzer": "standard"},
                "date_of_joining":   {"type": "date"},
                "nationality":       {"type": "keyword"},
                "gender":            {"type": "keyword"},
                "role_id":           {"type": "keyword"},

                # --- Reimbursement / expense ---
                "budget_period":      {"type": "keyword"},
                "transaction_date":   {"type": "date"},
                "paid_by":            {"type": "keyword"},
                "expense_entry_type": {"type": "keyword"},
                "bill_date":          {"type": "date"},

                # --- Assets ---
                "asset_value":         {"type": "double"},
                "acquisition_date":    {"type": "date"},
                "depreciation":        {"type": "keyword"},
                "asset_specification": {"type": "text", "analyzer": "english"},
                "original_value":      {"type": "double"},

                # --- Sales order / fulfillment ---
                "invoice_status":        {"type": "keyword"},
                "delivery_status":       {"type": "keyword"},
                "expiration_date":       {"type": "date"},
                "return_status":         {"type": "keyword"},
                "return_source":         {"type": "keyword"},
                "stages":                {"type": "keyword"},
                "expected_closing_date": {"type": "date"},
                "expected_revenue":      {"type": "double"},
                "probability":           {"type": "double"},
                "priority":              {"type": "keyword"},
                "promotion_type":        {"type": "keyword"},
                "start_date":            {"type": "date"},
                "end_date":              {"type": "date"},

                # --- Purchase fulfillment ---
                "billing_status":   {"type": "keyword"},
                "receiving_status": {"type": "keyword"},
                "rfq_type":         {"type": "keyword"},
                "lead_time":        {"type": "keyword"},
                "received_by":      {"type": "keyword"},
                "agreement_type":   {"type": "keyword"},
                "valid_up_to":      {"type": "date"},
                "refund_status":    {"type": "keyword"},

                # --- Inventory / items ---
                "item_type":      {"type": "keyword"},
                "sales_price":    {"type": "double"},
                "purchase_price": {"type": "double"},
                "upc_bar_code":   {"type": "keyword"},
                "costing_method": {"type": "keyword"},
                "city":           {"type": "keyword"},
                "summary":        {"type": "text", "analyzer": "english"},
                "transfer_type":  {"type": "keyword"},
                "description":    {"type": "text", "analyzer": "english"},

                # --- Manufacturing ---
                "material_status":       {"type": "keyword"},
                "production_start_date": {"type": "date"},
                "production_end_date":   {"type": "date"},
                "quantity":              {"type": "double"},
                "work_order_type":       {"type": "keyword"},

                # --- Equipment ---
                "equipment_cost":            {"type": "double"},
                "effective_date":            {"type": "date"},
                "warranty_expiration_date":  {"type": "date"},
                "maintenance_period":        {"type": "keyword"},

                # --- Gate register ---
                "transporter_name":      {"type": "keyword"},
                "driver_name":           {"type": "keyword"},
                "driver_contact_number": {"type": "keyword"},
                "entry_datetime":        {"type": "date"},
                "exit_datetime":         {"type": "date"},
                "entry_purpose":         {"type": "text", "analyzer": "english"},
                "exit_purpose":          {"type": "text", "analyzer": "english"},

                # --- Rental ---
                "received_quantity": {"type": "double"},
                "returned_quantity": {"type": "double"},

                # --- Drive ---
                "file_extension": {"type": "keyword"},
                "mime_type":      {"type": "keyword"},
                "drive_type":     {"type": "keyword"},
                "is_private":     {"type": "keyword"},
            }
        },
    }


def _normalise_date(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, (date, datetime)):
        return val.isoformat()[:10]
    s = str(val).strip()
    return s or None


def _resolve_party_name(row: dict) -> str | None:
    """Resolve party/person display name, trying multiple column patterns."""
    # Explicit join aliases set by most registry SQLs
    explicit = (
        row.get("customer_name") or row.get("vendor_name") or
        row.get("party_name") or row.get("employee_name")
    )
    if explicit:
        return explicit
    # Individual name fields (parties, employees, user)
    parts = [row.get("first_name"), row.get("middle_name"), row.get("last_name")]
    full_name = " ".join(p for p in parts if p).strip()
    if full_name:
        return full_name
    # Generic name fallback (companies, items, etc.)
    return row.get("name") or row.get("company_name") or None


def _build_doc_id(table: str, row: dict, strategy: str) -> str:
    if strategy == "junction":
        return f"{table}:{row['id']}:{row.get('company_id') or ''}"
    return f"{table}:{row['id']}"


class IndexerService:

    async def setup_search_pipeline(self) -> bool:
        """Create the hybrid-search normalization pipeline. Returns True on success.

        Requires the OpenSearch neural-search plugin. If the plugin is absent this
        call fails silently — search still works via the bool.should fallback.
        """
        loop = asyncio.get_running_loop()
        client = get_opensearch_client()
        body = {
            "description": "Normalize and blend BM25 + kNN scores for hybrid search",
            "phase_results_processors": [
                {
                    "normalization-processor": {
                        "normalization": {"technique": "min_max"},
                        "combination": {
                            "technique": "arithmetic_mean",
                            "parameters": {"weights": [0.3, 0.7]},
                        },
                    }
                }
            ],
        }
        try:
            await loop.run_in_executor(
                None,
                lambda: client.transport.perform_request(
                    "PUT",
                    f"/_search/pipeline/{_PIPELINE_NAME}",
                    body=body,
                ),
            )
            logfire.info("indexer pipeline created", pipeline=_PIPELINE_NAME)
            return True
        except Exception as exc:
            logfire.warning(
                "indexer pipeline creation skipped (neural-search plugin may not be installed)",
                pipeline=_PIPELINE_NAME,
                error=str(exc),
            )
            return False

    async def recreate_indices(self, client_id: str) -> None:
        """Drop and recreate one client's module indices, rebuilding the mapping from current config."""
        loop = asyncio.get_running_loop()
        client = get_opensearch_client()
        mapping = _index_mapping()
        for index_name in indices_for(client_id):
            exists = await loop.run_in_executor(
                None, lambda n=index_name: client.indices.exists(index=n)
            )
            if exists:
                await loop.run_in_executor(
                    None, lambda n=index_name: client.indices.delete(index=n)
                )
                logfire.info("indexer index dropped", index=index_name)
            await loop.run_in_executor(
                None,
                lambda n=index_name, m=mapping: client.indices.create(index=n, body=m),
            )
            logfire.info("indexer index created", index=index_name)
        await self.setup_search_pipeline()

    async def create_indices(self, client_id: str) -> None:
        """Create one client's module indices in OpenSearch if they don't already exist."""
        loop = asyncio.get_running_loop()
        client = get_opensearch_client()
        mapping = _index_mapping()

        for index_name in indices_for(client_id):
            exists = await loop.run_in_executor(
                None, lambda n=index_name: client.indices.exists(index=n)
            )
            if not exists:
                await loop.run_in_executor(
                    None,
                    lambda n=index_name, m=mapping: client.indices.create(index=n, body=m),
                )
                logfire.info("indexer index created", index=index_name)
        await self.setup_search_pipeline()

    async def sync(
        self,
        client_id: str,
        tables: list[str] | None = None,
        full_reindex: bool = False,
        recreate_indices: bool = False,
        job_id: str | None = None,
    ) -> tuple[int, int]:
        """Index the given tables (or all tables if None) for ONE client. Returns (indexed, errors)."""
        reg = resolve_registry(client_id)
        targets = tables if tables is not None else list(reg.keys())
        unknown = [t for t in targets if t not in reg]
        if unknown:
            raise ValueError(f"Unknown tables: {unknown}")

        started_at = datetime.now(timezone.utc).isoformat()
        t0 = time.perf_counter()

        if job_id:
            await _write_job_status(job_id, {
                "job_id": job_id, "client_id": client_id, "status": "running",
                "indexed": 0, "errors": 0,
                "total_tables": len(targets), "completed_tables": 0,
                "failed_tables": [], "started_at": started_at,
                "completed_at": None, "duration_ms": None,
            })

        if recreate_indices:
            await self.recreate_indices(client_id)
        else:
            await self.create_indices(client_id)

        total_indexed = 0
        total_errors = 0
        completed: list[str] = []
        failed: list[str] = []
        pending = list(targets)

        mode = "recreate+reindex" if recreate_indices else ("full reindex" if full_reindex else "upsert")
        logfire.info(
            f"indexer[{client_id}] {mode} started — {len(targets)} tables",
            client_id=client_id,
            mode=mode,
            tables=targets,
        )
        logfire.force_flush()

        for table in targets:
            pending.remove(table)
            try:
                indexed, errors = await self._sync_table(
                    client_id, table, reg[table], full_reindex
                )
                total_indexed += indexed
                total_errors += errors
                completed.append(table)
                done_count = len(completed)
                total_count = len(targets)
                pending_count = len(pending)
                logfire.info(
                    f"indexer[{client_id}] ✓ {table}: {indexed} docs "
                    f"({done_count}/{total_count} tables done, {pending_count} pending)",
                    client_id=client_id,
                    table=table,
                    indexed=indexed,
                    errors=errors,
                    tables_done=done_count,
                    pending=pending,
                )
            except Exception as exc:
                failed.append(table)
                logfire.error(
                    f"indexer[{client_id}] ✗ {table} FAILED: {exc} — pending: {pending or 'none'}",
                    client_id=client_id,
                    table=table,
                    error=str(exc),
                    failed=failed,
                    pending=pending,
                )
                total_errors += 1
            finally:
                logfire.force_flush()
                if job_id:
                    await _write_job_status(job_id, {
                        "job_id": job_id, "client_id": client_id, "status": "running",
                        "indexed": total_indexed, "errors": total_errors,
                        "total_tables": len(targets),
                        "completed_tables": len(completed) + len(failed),
                        "failed_tables": failed, "started_at": started_at,
                        "completed_at": None, "duration_ms": None,
                    })

        final_status = "partial" if failed else "ok"
        duration_ms = round((time.perf_counter() - t0) * 1000, 2)

        status = "PARTIAL" if failed else "OK"
        log_fn = logfire.warning if failed else logfire.info
        log_fn(
            f"indexer[{client_id}] sync {status}: {total_indexed} docs indexed across "
            f"{len(completed)}/{len(targets)} tables in {duration_ms/1000:.1f}s, "
            f"{len(failed)} FAILED: {failed or 'none'}",
            client_id=client_id,
            total_indexed=total_indexed,
            succeeded=len(completed),
            failed_count=len(failed),
            failed=failed,
            duration_ms=duration_ms,
        )
        logfire.force_flush()

        if job_id:
            await _write_job_status(job_id, {
                "job_id": job_id, "client_id": client_id, "status": final_status,
                "indexed": total_indexed, "errors": total_errors,
                "total_tables": len(targets),
                "completed_tables": len(completed) + len(failed),
                "failed_tables": failed, "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": duration_ms,
            })

        return total_indexed, total_errors

    async def _sync_table(
        self, client_id: str, table: str, cfg: dict, full_reindex: bool
    ) -> tuple[int, int]:
        loop = asyncio.get_running_loop()
        target_index = index_for(client_id, cfg["module"])

        if full_reindex:
            await self._delete_by_doc_type(table, target_index)

        rows = await loop.run_in_executor(
            None, lambda: execute_safe_query(cfg["sql"], client_id=client_id)
        )
        if not rows:
            logfire.info(
                f"indexer[{client_id}] {table}: 0 rows — nothing to index",
                client_id=client_id, table=table, index=target_index,
            )
            return 0, 0

        logfire.info(
            f"indexer[{client_id}] indexing {table} → {target_index}: {len(rows)} rows",
            client_id=client_id, table=table, index=target_index, total_rows=len(rows),
        )

        indexed = 0
        errors = 0
        client = get_opensearch_client()
        strategy = cfg["company_id_strategy"]
        get_amount = cfg.get("get_amount", lambda r: None)

        for start in range(0, len(rows), _BATCH_SIZE):
            batch = rows[start : start + _BATCH_SIZE]
            titles = [cfg["build_title"](r) for r in batch]
            texts = [cfg["build_text_content"](r) for r in batch]
            embed_inputs = [f"{t} {x}".strip() if t else x for t, x in zip(titles, texts)]
            embeddings = await embedder.embed_many(embed_inputs)

            bulk_body: list[dict] = []
            for row, title, text, embedding in zip(batch, titles, texts, embeddings):
                doc_id = _build_doc_id(table, row, strategy)
                company_id = row.get("company_id")
                raw_amount = get_amount(row)

                doc = {
                    # --- Core ---
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
                    "party_name":       _resolve_party_name(row),
                    "company_name":     row.get("company_name"),
                    "first_name":       row.get("first_name"),
                    "last_name":        row.get("last_name"),
                    "approval_status":  row.get("approval_status"),
                    "transaction_type": row.get("transaction_type"),
                    "email":            row.get("email") or row.get("email_ids"),
                    "phone":            row.get("phone") or row.get("contact_no"),
                    # --- Invoice / payment ---
                    "payment_status":          row.get("payment_status"),
                    "due_date":                _normalise_date(row.get("due_date")),
                    "amount_paid":             _to_float(row.get("amount_paid")),
                    "amount_due":              _to_float(row.get("amount_due")),
                    "supplier_invoice_number": row.get("supplier_invoice_number"),
                    "order_type":              row.get("order_type"),
                    "payment_type":            row.get("payment_type"),
                    "payment_method_type":     row.get("payment_method_type"),
                    "cheque_number":           row.get("cheque_number"),
                    "cheque_date":             _normalise_date(row.get("cheque_date")),
                    "is_reconciled":           _to_str(row.get("is_reconciled")),
                    "narration":               row.get("narration"),
                    "ref_type":                row.get("ref_type"),
                    "party_role":              row.get("party_role"),
                    "version":                 _to_str(row.get("version")),
                    "po_number":               row.get("po_number"),
                    # --- Party / company profile ---
                    "party_type":        row.get("party_type"),
                    "vat_number":        row.get("vat_number"),
                    "crn":               row.get("crn"),
                    "sales_lead_status": row.get("sales_lead_status"),
                    "sales_op_stage":    row.get("sales_op_stage"),
                    "credit_hold":       _to_str(row.get("credit_hold")),
                    "is_active":         _to_str(row.get("is_active")),
                    "address":           row.get("address"),
                    "date_of_joining":   _normalise_date(row.get("date_of_joining")),
                    "nationality":       row.get("nationality"),
                    "gender":            row.get("gender"),
                    "role_id":           _to_str(row.get("role_id")),
                    # --- Reimbursement / expense ---
                    "budget_period":      row.get("budget_period"),
                    "transaction_date":   _normalise_date(row.get("transaction_date")),
                    "paid_by":            row.get("paid_by"),
                    "expense_entry_type": row.get("expense_entry_type"),
                    "bill_date":          _normalise_date(row.get("bill_date")),
                    # --- Assets ---
                    "asset_value":         _to_float(row.get("asset_value")),
                    "acquisition_date":    _normalise_date(row.get("acquisition_date")),
                    "depreciation":        _to_str(row.get("depreciation")),
                    "asset_specification": row.get("asset_specification"),
                    "original_value":      _to_float(row.get("original_value")),
                    # --- Sales order / fulfillment ---
                    "invoice_status":        row.get("invoice_status"),
                    "delivery_status":       row.get("delivery_status"),
                    "expiration_date":       _normalise_date(row.get("expiration_date")),
                    "return_status":         row.get("return_status"),
                    "return_source":         row.get("return_source"),
                    "stages":                row.get("stages"),
                    "expected_closing_date": _normalise_date(row.get("expected_closing_date")),
                    "expected_revenue":      _to_float(row.get("expected_revenue")),
                    "probability":           _to_float(row.get("probability")),
                    "priority":              row.get("priority"),
                    "promotion_type":        row.get("promotion_type"),
                    "start_date":            _normalise_date(row.get("start_date")),
                    "end_date":              _normalise_date(row.get("end_date")),
                    # --- Purchase fulfillment ---
                    "billing_status":   row.get("billing_status"),
                    "receiving_status": row.get("receiving_status"),
                    "rfq_type":         row.get("rfq_type"),
                    "lead_time":        row.get("lead_time"),
                    "received_by":      row.get("received_by"),
                    "agreement_type":   row.get("agreement_type"),
                    "valid_up_to":      _normalise_date(row.get("valid_up_to")),
                    "refund_status":    row.get("refund_status"),
                    # --- Inventory / items ---
                    "item_type":      row.get("item_type"),
                    "sales_price":    _to_float(row.get("sales_price")),
                    "purchase_price": _to_float(row.get("purchase_price")),
                    "upc_bar_code":   row.get("upc_bar_code"),
                    "costing_method": row.get("costing_method"),
                    "city":           row.get("city"),
                    "summary":        row.get("summary"),
                    "transfer_type":  row.get("transfer_type"),
                    "description":    row.get("description"),
                    # --- Manufacturing ---
                    "material_status":       row.get("material_status"),
                    "production_start_date": _normalise_date(row.get("production_start_date")),
                    "production_end_date":   _normalise_date(row.get("production_end_date")),
                    "quantity":              _to_float(row.get("quantity")),
                    "work_order_type":       row.get("work_order_type"),
                    # --- Equipment ---
                    "equipment_cost":           _to_float(row.get("equipment_cost")),
                    "effective_date":           _normalise_date(row.get("effective_date")),
                    "warranty_expiration_date": _normalise_date(row.get("warranty_expiration_date")),
                    "maintenance_period":       row.get("maintenance_period"),
                    # --- Gate register ---
                    "transporter_name":      row.get("transporter_name"),
                    "driver_name":           row.get("driver_name"),
                    "driver_contact_number": row.get("driver_contact_number"),
                    "entry_datetime":        _normalise_date(row.get("entry_datetime")),
                    "exit_datetime":         _normalise_date(row.get("exit_datetime")),
                    "entry_purpose":         row.get("entry_purpose"),
                    "exit_purpose":          row.get("exit_purpose"),
                    # --- Rental ---
                    "received_quantity": _to_float(row.get("received_quantity")),
                    "returned_quantity": _to_float(row.get("returned_quantity")),
                    # --- Drive ---
                    "file_extension": row.get("file_extension"),
                    "mime_type":      row.get("mime_type"),
                    "drive_type":     row.get("drive_type"),
                    "is_private":     _to_str(row.get("is_private")),
                }
                bulk_body.append({"index": {"_index": target_index, "_id": doc_id}})
                bulk_body.append(doc)

            if not bulk_body:
                continue

            resp = await loop.run_in_executor(
                None, lambda b=bulk_body: client.bulk(body=b)
            )
            if resp.get("errors"):
                for item in resp.get("items", []):
                    if "error" in item.get("index", {}):
                        errors += 1
                    else:
                        indexed += 1
            else:
                indexed += len(bulk_body) // 2

            # Progress heartbeat every 250 docs (5 batches of 50) so a long table
            # visibly advances instead of going silent.
            done = min(start + _BATCH_SIZE, len(rows))
            if done < len(rows) and (start // _BATCH_SIZE) % 5 == 4:
                logfire.info(
                    f"indexer[{client_id}] {table}: {done}/{len(rows)} docs indexed",
                    client_id=client_id, table=table, done=done, total_rows=len(rows),
                )

        logfire.info(
            f"indexer[{client_id}] {table}: {indexed}/{len(rows)} docs indexed (done, {errors} errors)",
            client_id=client_id, table=table, indexed=indexed, total_rows=len(rows), errors=errors,
        )
        return indexed, errors

    async def _delete_by_doc_type(self, table: str, index: str) -> None:
        loop = asyncio.get_running_loop()
        client = get_opensearch_client()
        body = {"query": {"term": {"doc_type": table}}}
        await loop.run_in_executor(
            None,
            lambda: client.delete_by_query(index=index, body=body, conflicts="proceed"),
        )


indexer = IndexerService()

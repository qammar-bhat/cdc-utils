"""Shared utilities for the Smart Search index registry."""
from __future__ import annotations
from typing import Any

_SKIP_FIELDS = frozenset({
    "id", "company_id", "is_deleted", "deleted_at", "deleted_by",
    "created_at", "updated_at", "created_by", "updated_by",
    "password", "remember_token", "attachment",
})

_AMOUNT_COLS = (
    "grand_total", "total_amount", "total_invoice_amount", "amount", "net_amount",
    "purchase_amount", "purchase_price", "total_value", "budget_amount",
    "payment_amount",
)


def prose(doc_label: str, row: dict, fields: list[tuple[str, str]]) -> str:
    """Build natural-language text: 'This is a {doc_label} where {label} is {val}, ...'

    Each element of `fields` is a (human_label, column_name) pair.
    Null / empty column values are silently skipped.
    """
    pairs = [
        (label, str(v).strip())
        for label, col in fields
        if (v := row.get(col)) is not None and str(v).strip()
    ]
    if not pairs:
        return f"This is a {doc_label}"
    return f"This is a {doc_label} where " + ", ".join(f"{lbl} is {val}" for lbl, val in pairs)


def build_doc_title(*parts: Any) -> str:
    """Join non-None non-empty parts with ' · ' for document titles.

    Usage: build_doc_title("Sales Invoice", r.get("series_number"), r.get("customer_name"))
    → "Sales Invoice · INV-001 · Samsung" (None / empty parts are dropped, so no orphan '·')
    """
    return " · ".join(s for p in parts if p is not None and (s := str(p).strip()))


def build_text_content(row: dict) -> str:
    """Legacy generic fallback — builds a 'key: value' dump from all non-skipped columns.

    Prefer per-table `prose()` builders for better embedding quality.
    """
    parts = []
    for k, v in row.items():
        if k in _SKIP_FIELDS:
            continue
        if k.endswith("_id"):
            continue
        if v is None:
            continue
        s = str(v).strip()
        if s:
            label = k.replace("_", " ")
            parts.append(f"{label}: {s}")
    return " ".join(parts)


def extract_amount(row: dict) -> float | None:
    """Try common amount column names in priority order; return first non-null numeric value."""
    for col in _AMOUNT_COLS:
        v = row.get(col)
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                pass
    return None

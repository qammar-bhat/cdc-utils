"""CDC row-refetch id-column resolution.

Regression guard for the bug where `FROM journal_entries WHERE ...` (no alias)
captured "WHERE" as the alias → `WHERE.id` → broken refetch → events dropped.
"""
from __future__ import annotations

from indexer.cdc_handler import _SQL_NON_ALIAS, _id_column_for
from indexer.registry.overrides import resolve_registry


def test_real_alias_is_used():
    assert _id_column_for("purchase_invoices", "SELECT * FROM purchase_invoices pi LEFT JOIN parties p ON p.id=pi.vendor_id WHERE pi.is_deleted=0") == "pi.id"


def test_no_alias_falls_back_to_bare_id():
    assert _id_column_for("journal_entries", "SELECT * FROM journal_entries WHERE is_deleted = 0") == "id"


def test_join_keyword_not_taken_as_alias():
    assert _id_column_for("items", "SELECT * FROM items LEFT JOIN item_companies ic ON ic.item_id=items.id") == "id"


def test_no_where_no_alias():
    assert _id_column_for("drive", "SELECT * FROM drive") == "id"


def test_all_registry_tables_resolve_safely():
    """Every tenant's every table must resolve to a real alias or bare `id` —
    never a SQL keyword."""
    for client in ("spar", "dev_env"):
        for table, cfg in resolve_registry(client).items():
            id_col = _id_column_for(table, cfg["sql"].strip().rstrip(";"))
            assert id_col.endswith(".id") or id_col == "id"
            alias = id_col[:-3] if id_col != "id" else None
            assert alias is None or alias.upper() not in _SQL_NON_ALIAS, (
                f"{client}/{table} resolved to keyword alias {id_col!r}"
            )

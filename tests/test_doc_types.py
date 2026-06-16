"""Index naming + doc_type→module mapping (tenant isolation)."""
from __future__ import annotations

from indexer.doc_types import (
    ALL_MODULES,
    DOC_TYPE_TO_MODULE,
    index_for,
    indices_for,
)
from indexer.registry import TABLE_REGISTRY


def test_index_for_is_client_scoped():
    assert index_for("spar", "account") == "spar_account"
    assert index_for("dev_env", "sales") == "dev_env_sales"


def test_indices_for_covers_all_modules():
    idx = indices_for("spar")
    assert len(idx) == len(ALL_MODULES)
    assert all(i.startswith("spar_") for i in idx)


def test_two_tenants_never_share_an_index():
    assert set(indices_for("spar")).isdisjoint(set(indices_for("dev_env")))


def test_doc_type_to_module_covers_registry():
    assert set(DOC_TYPE_TO_MODULE) == set(TABLE_REGISTRY)
    for table, cfg in TABLE_REGISTRY.items():
        assert DOC_TYPE_TO_MODULE[table] == cfg["module"]


def test_all_modules_sorted_and_unique():
    assert ALL_MODULES == sorted(set(ALL_MODULES))

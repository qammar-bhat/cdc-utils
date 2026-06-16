"""doc_types.py — tenant-aware index naming and doc_type→module mapping.

The hub's READ path (searcher, copilot tools) needs only two things from the
indexing world: which modules exist, and which module a doc_type belongs to —
so it can compute per-tenant index names: {client_id}_{module}.

While the full table registry still lives in this repo it is the source of
truth here; once indexing is extracted to the indexer microservice, this file
keeps the same public API with a hardcoded map (must be kept in sync with the
indexer service's registry).
"""

from __future__ import annotations

from indexer.registry import MODULE_TO_DOC_TYPES, TABLE_REGISTRY

ALL_MODULES: list[str] = sorted(MODULE_TO_DOC_TYPES.keys())

DOC_TYPE_TO_MODULE: dict[str, str] = {
    table: cfg["module"] for table, cfg in TABLE_REGISTRY.items()
}


def index_for(client_id: str, module: str) -> str:
    """OpenSearch index name for one client's module."""
    return f"{client_id}_{module}"


def indices_for(client_id: str) -> list[str]:
    """All of one client's index names."""
    return [index_for(client_id, m) for m in ALL_MODULES]

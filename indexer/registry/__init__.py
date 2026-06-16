"""Smart Search registry — combines all module registries into a single lookup."""
from __future__ import annotations

from ._utils import build_text_content as build_text_content
from .account import ACCOUNT_REGISTRY
from .document import DOCUMENT_REGISTRY
from .inventory import INVENTORY_REGISTRY
from .manufacturing import MANUFACTURING_REGISTRY
from .purchase import PURCHASE_REGISTRY
from .rental import RENTAL_REGISTRY
from .sales import SALES_REGISTRY

TABLE_REGISTRY: dict[str, dict] = {
    **ACCOUNT_REGISTRY,
    **INVENTORY_REGISTRY,
    **SALES_REGISTRY,
    **PURCHASE_REGISTRY,
    **MANUFACTURING_REGISTRY,
    **RENTAL_REGISTRY,
    **DOCUMENT_REGISTRY,
}

ALL_INDICES: list[str] = sorted({cfg["index"] for cfg in TABLE_REGISTRY.values()})

MODULE_TO_DOC_TYPES: dict[str, list[str]] = {}
for _table, _cfg in TABLE_REGISTRY.items():
    MODULE_TO_DOC_TYPES.setdefault(_cfg["module"], []).append(_table)

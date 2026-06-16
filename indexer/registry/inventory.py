"""Index registry — Inventory module (5 tables)."""
from __future__ import annotations

from ._utils import build_doc_title, prose

INDEX = "erpforce_inventory"
MODULE = "inventory"

INVENTORY_REGISTRY: dict[str, dict] = {}


# ======= ITEMS =======
INVENTORY_REGISTRY["items"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT i.*, i.type AS item_type, ic.company_id
        FROM items i
        LEFT JOIN item_companies ic ON ic.item_id = i.id
        WHERE i.is_deleted = 0
    """,
    "build_title":        lambda r: build_doc_title("Item", r.get("name")),
    "get_reference":      lambda r: r.get("sku"),
    "get_status":         lambda r: None,
    "get_date":           lambda r: None,
    "get_amount":         lambda r: r.get("sales_price"),
    "build_text_content": lambda r: prose("item product", r, [
        ("name",         "name"),
        ("sku",          "sku"),
        ("item type",    "item_type"),
        ("brand",        "brand"),
        ("upc bar code", "upc_bar_code"),
        ("description",  "description"),
    ]),
    "company_id_strategy": "junction",
}


# ======= WAREHOUSE LOCATION =======
INVENTORY_REGISTRY["warehouse_location"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT *
        FROM warehouse_location
        WHERE is_deleted = 0
    """,
    "build_title":        lambda r: build_doc_title("Warehouse", r.get("name")),
    "get_reference":      lambda r: r.get("short_name"),
    "get_status":         lambda r: None,
    "get_date":           lambda r: None,
    "build_text_content": lambda r: prose("warehouse location", r, [
        ("name",       "name"),
        ("short name", "short_name"),
        ("address",    "address"),
    ]),
    "company_id_strategy": "direct",
}


# ======= INVENTORY ADJUSTMENTS =======
INVENTORY_REGISTRY["inventory_adjustments"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT ia.*, wl.name AS location_name
        FROM inventory_adjustments ia
        LEFT JOIN warehouse_location wl ON wl.id = ia.location
        WHERE ia.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Inventory Adjustment", r.get("reason"), r.get("location_name")
    ),
    "get_reference":      lambda r: None,
    "get_status":         lambda r: None,
    "get_date":           lambda r: r.get("date"),
    "build_text_content": lambda r: prose("inventory adjustment stock adjustment", r, [
        ("reason",   "reason"),
        ("location", "location_name"),
        ("narration","narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= BIN TRANSFERS =======
INVENTORY_REGISTRY["bin_transfers"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT *
        FROM bin_transfers
        WHERE is_deleted = 0
    """,
    "build_title":        lambda r: build_doc_title("Bin Transfer", r.get("status")),
    "get_reference":      lambda r: None,
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date"),
    "build_text_content": lambda r: prose("bin transfer", r, [
        ("status",   "status"),
        ("narration","narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= STOCK TRANSFERS =======
INVENTORY_REGISTRY["stock_transfers"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT st.*,
               src.name AS source_location_name,
               dst.name AS destination_location_name
        FROM stock_transfers st
        LEFT JOIN warehouse_location src ON src.id = st.source_location_id
        LEFT JOIN warehouse_location dst ON dst.id = st.destination_location_id
        WHERE st.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Stock Transfer",
        r.get("operation_type"),
        r.get("source_location_name"),
        r.get("destination_location_name"),
    ),
    "get_reference":      lambda r: None,
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date"),
    "build_text_content": lambda r: prose("stock transfer", r, [
        ("operation type",       "operation_type"),
        ("source location",      "source_location_name"),
        ("destination location", "destination_location_name"),
        ("transfer type",        "transfer_type"),
        ("status",               "status"),
        ("description",          "description"),
    ]),
    "company_id_strategy": "direct",
}

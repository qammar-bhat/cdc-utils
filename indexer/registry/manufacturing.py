"""Index registry — Manufacturing module (7 tables)."""
from __future__ import annotations

from ._utils import build_doc_title, prose

INDEX = "erpforce_manufacturing"
MODULE = "manufacturing"

MANUFACTURING_REGISTRY: dict[str, dict] = {}


# ======= MF WORK ORDERS =======
MANUFACTURING_REGISTRY["mf_work_orders"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT wo.*, wo.type AS work_order_type, i.name AS item_name
        FROM mf_work_orders wo
        LEFT JOIN items i ON i.id = wo.item_id
        WHERE wo.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Work Order", r.get("series_number"), r.get("item_name")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date"),
    "build_text_content": lambda r: prose("work order manufacturing", r, [
        ("series number",   "series_number"),
        ("item",            "item_name"),
        ("status",          "status"),
        ("material status", "material_status"),
        ("reference number","reference_number"),
        ("narration",       "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= MF BOM =======
MANUFACTURING_REGISTRY["mf_bom"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT b.*, i.name AS item_name, bc.company_id
        FROM mf_bom b
        LEFT JOIN items i ON i.id = b.item_id
        INNER JOIN mf_bom_companies bc ON bc.bom_id = b.id
        WHERE b.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Bill of Materials", r.get("name"), r.get("item_name")
    ),
    "get_reference":      lambda r: r.get("version_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("start_date"),
    "build_text_content": lambda r: prose("bill of materials bom", r, [
        ("name",           "name"),
        ("item",           "item_name"),
        ("version number", "version_number"),
        ("status",         "status"),
        ("narration",      "narration"),
    ]),
    "company_id_strategy": "junction",
}


# ======= MF BUILD ORDERS =======
MANUFACTURING_REGISTRY["mf_build_orders"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT bo.*, i.name AS item_name
        FROM mf_build_orders bo
        LEFT JOIN items i ON i.id = bo.item_id
        WHERE bo.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Build Order", r.get("series_number"), r.get("item_name")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date"),
    "build_text_content": lambda r: prose("build order assembly", r, [
        ("series number", "series_number"),
        ("item",          "item_name"),
        ("status",        "status"),
        ("narration",     "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= MF JOB CARDS =======
MANUFACTURING_REGISTRY["mf_job_cards"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT jc.*, wo.series_number AS work_order_number
        FROM mf_job_cards jc
        LEFT JOIN mf_work_orders wo ON wo.id = jc.work_order_id
        WHERE jc.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Job Card", r.get("series_number"), r.get("work_order_number")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date"),
    "build_text_content": lambda r: prose("job card production", r, [
        ("series number",    "series_number"),
        ("work order number","work_order_number"),
        ("status",           "status"),
        ("material status",  "material_status"),
        ("narration",        "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= MF PRODUCTION PLAN =======
MANUFACTURING_REGISTRY["mf_production_plan"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT *
        FROM mf_production_plan
        WHERE is_deleted = 0
    """,
    "build_title":        lambda r: build_doc_title("Production Plan", r.get("series_number")),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date"),
    "build_text_content": lambda r: prose("production plan", r, [
        ("series number", "series_number"),
    ]),
    "company_id_strategy": "direct",
}


# ======= MF EQUIPMENTS =======
MANUFACTURING_REGISTRY["mf_equipments"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT e.*,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS vendor_name
        FROM mf_equipments e
        LEFT JOIN parties p ON p.id = e.vendor_id
        WHERE e.is_deleted = 0
    """,
    "build_title":        lambda r: build_doc_title("Equipment", r.get("name")),
    "get_reference":      lambda r: r.get("serial_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("effective_date"),
    "get_amount":         lambda r: r.get("equipment_cost"),
    "build_text_content": lambda r: prose("equipment machinery", r, [
        ("name",               "name"),
        ("serial number",      "serial_number"),
        ("vendor",             "vendor_name"),
        ("status",             "status"),
        ("used by",            "used_by"),
        ("model",              "model"),
        ("maintenance period", "maintenance_period"),
        ("narration",          "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= MF GATE REGISTERS =======
MANUFACTURING_REGISTRY["mf_gate_registers"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT *
        FROM mf_gate_registers
        WHERE is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Gate Register", r.get("series_number"), r.get("transporter_name")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: None,
    "get_date":           lambda r: r.get("record_date"),
    "build_text_content": lambda r: prose("gate register entry exit", r, [
        ("series number",       "series_number"),
        ("transporter",         "transporter_name"),
        ("driver",              "driver_name"),
        ("driver contact",      "driver_contact_number"),
        ("identification number","identification_number"),
        ("entry purpose",       "entry_purpose"),
        ("entry material",      "entry_material"),
        ("exit purpose",        "exit_purpose"),
    ]),
    "company_id_strategy": "direct",
}

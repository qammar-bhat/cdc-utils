"""Index registry — Rental module (2 tables)."""
from __future__ import annotations

from ._utils import build_doc_title, prose

INDEX = "erpforce_rental"
MODULE = "rental"

RENTAL_REGISTRY: dict[str, dict] = {}


# ======= RN CROSS HIRE SUMMARY =======
RENTAL_REGISTRY["rn_cross_hire_summary"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT chs.*,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS party_name,
               p.company_id
        FROM rn_cross_hire_summary chs
        LEFT JOIN parties p ON p.id = chs.vendor_id
        WHERE chs.is_deleted = 0
    """,
    "build_title":        lambda r: build_doc_title("Cross Hire", r.get("party_name")),
    "get_reference":      lambda r: str(r["id"]) if r.get("id") else None,
    "get_status":         lambda r: None,
    "get_date":           lambda r: r.get("date"),
    "get_amount":         lambda r: None,
    "build_text_content": lambda r: prose("cross hire rental", r, [
        ("party", "party_name"),
    ]),
    "company_id_strategy": "direct",
}


# ======= RN DELIVERY ORDER GRN =======
RENTAL_REGISTRY["rn_delivery_order_grn"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT grn.*, grn.receipt_date AS date,
               COALESCE(grn.company_id, p.company_id) AS company_id,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS party_name
        FROM rn_delivery_order_grn grn
        LEFT JOIN parties p ON p.id = grn.customer_id
        WHERE grn.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Rental Return GRN", r.get("series_number"), r.get("party_name")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date"),
    "build_text_content": lambda r: prose("rental return delivery receipt", r, [
        ("series number", "series_number"),
        ("party",         "party_name"),
        ("status",        "status"),
        ("po number",     "po_number"),
        ("narration",     "narration"),
    ]),
    "company_id_strategy": "direct",
}

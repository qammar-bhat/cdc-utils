"""Index registry — Purchase module (8 tables)."""
from __future__ import annotations

from ._utils import build_doc_title, extract_amount, prose

INDEX = "erpforce_purchase"
MODULE = "purchase"

PURCHASE_REGISTRY: dict[str, dict] = {}


# ======= PR PURCHASE ORDERS =======
PURCHASE_REGISTRY["pr_purchase_orders"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT po.*,
               COALESCE(po.company_id, p.company_id) AS company_id,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS vendor_name
        FROM pr_purchase_orders po
        LEFT JOIN parties p ON p.id = po.supplier_id
        WHERE po.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Purchase Order", r.get("series_number"), r.get("vendor_name")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date"),
    "get_amount":         extract_amount,
    "build_text_content": lambda r: prose("purchase order", r, [
        ("series number",    "series_number"),
        ("vendor",           "vendor_name"),
        ("status",           "status"),
        ("billing status",   "billing_status"),
        ("receiving status", "receiving_status"),
        ("return status",    "return_status"),
        ("order type",       "order_type"),
        ("narration",        "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= PR PURCHASE REQUESTS =======
PURCHASE_REGISTRY["pr_purchase_requests"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT pr.*, pr.status AS approval_status, d.name AS department_name,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS vendor_name
        FROM pr_purchase_requests pr
        LEFT JOIN department d ON d.id = pr.department_id
        LEFT JOIN parties p ON p.id = pr.vendor_id
        WHERE pr.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Purchase Request", r.get("series_number"),
        r.get("vendor_name") or r.get("department_name"),
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: None,
    "get_date":           lambda r: r.get("date"),
    "build_text_content": lambda r: prose("purchase request", r, [
        ("series number",  "series_number"),
        ("department",     "department_name"),
        ("approval status","approval_status"),
        ("narration",      "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= PR RFQS =======
PURCHASE_REGISTRY["pr_rfqs"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT rfq.*, rfq.type AS rfq_type,
               COALESCE(rfq.company_id, p.company_id) AS company_id,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS vendor_name
        FROM pr_rfqs rfq
        LEFT JOIN parties p ON p.id = rfq.vendor_id
        WHERE rfq.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "RFQ", r.get("series_number"), r.get("vendor_name")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date"),
    "build_text_content": lambda r: prose("request for quotation rfq", r, [
        ("series number",   "series_number"),
        ("vendor",          "vendor_name"),
        ("status",          "status"),
        ("rfq type",        "rfq_type"),
        ("reference number","reference_number"),
        ("narration",       "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= PR RFQ RESPONSES =======
PURCHASE_REGISTRY["pr_rfq_responses"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT rr.*,
               COALESCE(rr.company_id, p.company_id) AS company_id,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS vendor_name
        FROM pr_rfq_responses rr
        LEFT JOIN parties p ON p.id = rr.vendor_id
        WHERE rr.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "RFQ Response", r.get("vendor_name"), r.get("reference_number")
    ),
    "get_reference":      lambda r: r.get("reference_number"),
    "get_status":         lambda r: None,
    "get_date":           lambda r: r.get("date"),
    "get_amount":         extract_amount,
    "build_text_content": lambda r: prose("rfq response quotation", r, [
        ("vendor",           "vendor_name"),
        ("reference number", "reference_number"),
        ("narration",        "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= PR PURCHASE ORDER GRNS =======
PURCHASE_REGISTRY["pr_purchase_order_grns"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT grn.*, grn.grn_date AS date,
               COALESCE(grn.company_id, p.company_id) AS company_id,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS vendor_name
        FROM pr_purchase_order_grns grn
        LEFT JOIN parties p ON p.id = grn.vendor_id
        WHERE grn.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Purchase GRN", r.get("series_number"), r.get("vendor_name")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: None,
    "get_date":           lambda r: r.get("date"),
    "build_text_content": lambda r: prose("purchase goods receipt grn", r, [
        ("series number", "series_number"),
        ("vendor",        "vendor_name"),
        ("narration",     "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= PR VRAS =======
PURCHASE_REGISTRY["pr_vras"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT vra.*,
               COALESCE(vra.company_id, p.company_id) AS company_id,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS vendor_name
        FROM pr_vras vra
        LEFT JOIN parties p ON p.id = vra.vendor_id
        WHERE vra.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Vendor Return", r.get("series_number"), r.get("vendor_name")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date"),
    "get_amount":         extract_amount,
    "build_text_content": lambda r: prose("vendor return purchase return", r, [
        ("series number",   "series_number"),
        ("vendor",          "vendor_name"),
        ("status",          "status"),
        ("refund status",   "refund_status"),
        ("reference number","reference_number"),
        ("narration",       "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= PR DELIVERY ORDERS =======
PURCHASE_REGISTRY["pr_delivery_orders"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT pdo.*,
               COALESCE(pdo.company_id, p.company_id) AS company_id,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS vendor_name
        FROM pr_delivery_orders pdo
        LEFT JOIN parties p ON p.id = pdo.vendor_id
        WHERE pdo.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Purchase Delivery Order", r.get("series_number"), r.get("vendor_name")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date"),
    "build_text_content": lambda r: prose("purchase delivery order", r, [
        ("series number", "series_number"),
        ("vendor",        "vendor_name"),
        ("status",        "status"),
        ("narration",     "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= PR PURCHASE AGREEMENTS =======
PURCHASE_REGISTRY["pr_purchase_agreements"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT pa.*,
               COALESCE(pa.company_id, p.company_id) AS company_id,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS vendor_name
        FROM pr_purchase_agreements pa
        LEFT JOIN parties p ON p.id = pa.vendor_id
        WHERE pa.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Purchase Agreement", r.get("name"), r.get("vendor_name")
    ),
    "get_reference":      lambda r: None,
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date"),
    "get_amount":         extract_amount,
    "build_text_content": lambda r: prose("purchase agreement contract", r, [
        ("name",           "name"),
        ("vendor",         "vendor_name"),
        ("agreement type", "agreement_type"),
        ("status",         "status"),
        ("instructions",   "instructions"),
        ("narration",      "narration"),
    ]),
    "company_id_strategy": "direct",
}

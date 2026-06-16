"""Index registry — Sales module (7 tables)."""
from __future__ import annotations

from ._utils import build_doc_title, extract_amount, prose

INDEX = "erpforce_sales"
MODULE = "sales"

SALES_REGISTRY: dict[str, dict] = {}


# ======= SL SALES ORDERS =======
SALES_REGISTRY["sl_sales_orders"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT so.*,
               COALESCE(so.company_id, p.company_id) AS company_id,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS customer_name
        FROM sl_sales_orders so
        LEFT JOIN parties p ON p.id = so.customer_id
        WHERE so.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Sales Order", r.get("series_number"), r.get("customer_name")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date"),
    "get_amount":         extract_amount,
    "build_text_content": lambda r: prose("sales order", r, [
        ("series number",   "series_number"),
        ("customer",        "customer_name"),
        ("status",          "status"),
        ("invoice status",  "invoice_status"),
        ("delivery status", "delivery_status"),
        ("return status",   "return_status"),
        ("transaction type","transaction_type"),
        ("po number",       "po_number"),
        ("narration",       "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= SL QUOTATION =======
SALES_REGISTRY["sl_quotation"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT q.*,
               COALESCE(q.company_id, p.company_id) AS company_id,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS customer_name
        FROM sl_quotation q
        LEFT JOIN parties p ON p.id = q.party_id
        WHERE q.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Quotation", r.get("reference_no"), r.get("customer_name")
    ),
    "get_reference":      lambda r: r.get("reference_no"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date"),
    "get_amount":         extract_amount,
    "build_text_content": lambda r: prose("quotation", r, [
        ("reference number", "reference_no"),
        ("customer",         "customer_name"),
        ("status",           "status"),
        ("transaction type", "transaction_type"),
        ("narration",        "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= SL DELIVERY ORDERS =======
SALES_REGISTRY["sl_delivery_orders"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT do.*,
               COALESCE(do.company_id, p.company_id) AS company_id,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS customer_name
        FROM sl_delivery_orders do
        LEFT JOIN parties p ON p.id = do.customer_id
        WHERE do.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Delivery Order", r.get("series_number"), r.get("customer_name")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date"),
    "get_amount":         extract_amount,
    "build_text_content": lambda r: prose("delivery order", r, [
        ("series number", "series_number"),
        ("customer",      "customer_name"),
        ("status",        "status"),
        ("narration",     "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= SL CUSTOMER RETURNS =======
SALES_REGISTRY["sl_customer_returns"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT cr.*,
               COALESCE(cr.company_id, p.company_id) AS company_id,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS customer_name
        FROM sl_customer_returns cr
        LEFT JOIN parties p ON p.id = cr.customer_id
        WHERE cr.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Customer Return", r.get("series_number"), r.get("customer_name")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date"),
    "get_amount":         extract_amount,
    "build_text_content": lambda r: prose("customer return", r, [
        ("series number",  "series_number"),
        ("customer",       "customer_name"),
        ("status",         "status"),
        ("return source",  "return_source"),
        ("reference number","reference_number"),
        ("narration",      "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= SL CUSTOMER RETURN GRN =======
SALES_REGISTRY["sl_customer_return_grn"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT grn.*,
               COALESCE(grn.company_id, p.company_id) AS company_id,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS customer_name
        FROM sl_customer_return_grn grn
        LEFT JOIN parties p ON p.id = grn.customer_id
        WHERE grn.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Customer Return Receipt", r.get("customer_name"), r.get("series_number")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: None,
    "get_date":           lambda r: r.get("date"),
    "build_text_content": lambda r: prose("customer return receipt", r, [
        ("customer",        "customer_name"),
        ("reference number","series_number"),
        ("narration",       "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= SL OPPORTUNITY PARTIES =======
SALES_REGISTRY["sl_opportunity_parties"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT op.*,
               COALESCE(op.company_id, p.company_id) AS company_id,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS party_name
        FROM sl_opportunity_parties op
        LEFT JOIN parties p ON p.id = op.party_id
        WHERE op.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Sales Opportunity", r.get("party_name"), r.get("stages")
    ),
    "get_reference":      lambda r: None,
    "get_status":         lambda r: None,
    "get_date":           lambda r: r.get("expected_closing_date"),
    "get_amount":         lambda r: r.get("expected_revenue"),
    "build_text_content": lambda r: prose("sales opportunity", r, [
        ("party",    "party_name"),
        ("stage",    "stages"),
        ("narration","narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= SL PROMOTIONS =======
SALES_REGISTRY["sl_promotions"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT *
        FROM sl_promotions
        WHERE is_deleted = 0
    """,
    "build_title":        lambda r: build_doc_title("Promotion", r.get("name")),
    "get_reference":      lambda r: None,
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("start_date"),
    "build_text_content": lambda r: prose("promotion", r, [
        ("name",           "name"),
        ("promotion type", "promotion_type"),
        ("status",         "status"),
        ("narration",      "narration"),
    ]),
    "company_id_strategy": "direct",
}

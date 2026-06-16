"""Index registry — Account module (15 tables)."""
from __future__ import annotations

from ._utils import build_doc_title, extract_amount, prose

INDEX = "erpforce_account"
MODULE = "account"

ACCOUNT_REGISTRY: dict[str, dict] = {}


# ======= SALES INVOICES =======
ACCOUNT_REGISTRY["sales_invoices"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT si.*,
               COALESCE(si.company_id, p.company_id) AS company_id,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS customer_name
        FROM sales_invoices si
        LEFT JOIN parties p ON p.id = si.customer_id
        WHERE si.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Sales Invoice", r.get("series_number"), r.get("customer_name")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: None,
    "get_date":           lambda r: r.get("date"),
    "get_amount":         extract_amount,
    "build_text_content": lambda r: prose("sales invoice", r, [
        ("series number",    "series_number"),
        ("customer",         "customer_name"),
        ("approval status",  "approval_status"),
        ("payment status",   "payment_status"),
        ("transaction type", "transaction_type"),
        ("narration",        "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= PURCHASE INVOICES =======
ACCOUNT_REGISTRY["purchase_invoices"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT pi.*, pi.bill_date AS date,
               COALESCE(pi.company_id, p.company_id) AS company_id,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS vendor_name
        FROM purchase_invoices pi
        LEFT JOIN parties p ON p.id = pi.vendor_id
        WHERE pi.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Purchase Invoice", r.get("series_number"), r.get("vendor_name")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: None,
    "get_date":           lambda r: r.get("date"),
    "get_amount":         extract_amount,
    "build_text_content": lambda r: prose("purchase invoice", r, [
        ("series number",           "series_number"),
        ("vendor",                  "vendor_name"),
        ("approval status",         "approval_status"),
        ("payment status",          "payment_status"),
        ("supplier invoice number", "supplier_invoice_number"),
        ("narration",               "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= PAYMENT ENTRIES =======
ACCOUNT_REGISTRY["payment_entries"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT pe.*, pe.type AS payment_method_type, je.company_id
        FROM payment_entries pe
        LEFT JOIN journal_entries je ON je.id = pe.entry_id
        WHERE pe.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Payment Entry", r.get("series_number"), r.get("payment_method_type")
    ),
    "get_reference":      lambda r: r.get("reference_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date"),
    "get_amount":         extract_amount,
    "build_text_content": lambda r: prose("payment entry", r, [
        ("series number",       "series_number"),
        ("payment type",        "payment_type"),
        ("party type",          "party_type"),
        ("approval status",     "approval_status"),
        ("status",              "status"),
        ("payment method type", "payment_method_type"),
        ("narration",           "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= CREDIT NOTES =======
ACCOUNT_REGISTRY["credit_notes"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT cn.*, cn.credit_note_date AS date, cn.party AS party_role,
               COALESCE(cn.company_id, p.company_id) AS company_id,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS party_name
        FROM credit_notes cn
        LEFT JOIN parties p ON p.id = cn.party_id
        WHERE cn.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Credit Note", r.get("series_number"), r.get("party_name")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date"),
    "get_amount":         extract_amount,
    "build_text_content": lambda r: prose("credit note", r, [
        ("series number", "series_number"),
        ("party",         "party_name"),
        ("party role",    "party_role"),
        ("status",        "status"),
        ("narration",     "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= DEBIT NOTES =======
ACCOUNT_REGISTRY["debit_notes"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT dn.*, dn.debit_note_date AS date, dn.party AS party_role,
               COALESCE(dn.company_id, p.company_id) AS company_id,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS party_name
        FROM debit_notes dn
        LEFT JOIN parties p ON p.id = dn.party_id
        WHERE dn.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Debit Note", r.get("series_number"), r.get("party_name")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date"),
    "get_amount":         extract_amount,
    "build_text_content": lambda r: prose("debit note", r, [
        ("series number", "series_number"),
        ("party",         "party_name"),
        ("party role",    "party_role"),
        ("status",        "status"),
        ("narration",     "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= JOURNAL ENTRIES =======
ACCOUNT_REGISTRY["journal_entries"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT *, posting_date AS date
        FROM journal_entries
        WHERE is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Journal Entry", r.get("series_number"), r.get("narration")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date"),
    "build_text_content": lambda r: prose("journal entry", r, [
        ("series number", "series_number"),
        ("status",        "status"),
        ("ref type",      "ref_type"),
        ("narration",     "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= PARTIES =======

def _party_display_name(r: dict) -> str | None:
    """company_name takes priority; fall back to whatever name parts exist."""
    if r.get("company_name"):
        return r["company_name"]
    parts = [r.get("first_name"), r.get("middle_name"), r.get("last_name")]
    joined = " ".join(p for p in parts if p)
    return joined or None


def _party_text_content(r: dict) -> str:
    """'This is a party with company name X' (or 'with name X' for individuals),
    followed by any other available attributes."""
    display_name = _party_display_name(r)
    name_label = "company name" if r.get("company_name") else "name"

    intro = (
        f"This is a party with {name_label} {display_name}"
        if display_name
        else "This is a party"
    )

    extra_fields = [
        ("party type",              r.get("party_type")),
        ("vat number",              r.get("vat_number")),
        ("crn",                     r.get("crn")),
        ("email",                   r.get("email")),
        ("sales lead status",       r.get("sales_lead_status")),
        ("sales opportunity stage", r.get("sales_op_stage")),
    ]
    extras = ", ".join(
        f"{label} is {val}" for label, val in extra_fields if val is not None and str(val).strip()
    )

    return f"{intro}, {extras}" if extras else intro


ACCOUNT_REGISTRY["parties"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT p.*, p.type AS party_type
        FROM parties p
        WHERE p.is_deleted = 0
    """,
    "build_title":        lambda r: build_doc_title("Party", _party_display_name(r)),
    "get_reference":      lambda r: None,
    "get_status":         lambda r: None,
    "get_date":           lambda r: None,
    "build_text_content": _party_text_content,
    "company_id_strategy": "direct",
}


# ======= COMPANIES =======
ACCOUNT_REGISTRY["companies"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT *, id AS company_id
        FROM companies
        WHERE is_deleted = 0
    """,
    "build_title":        lambda r: build_doc_title("Company", r.get("company_name")),
    "get_reference":      lambda r: r.get("crn"),
    "get_status":         lambda r: None,
    "get_date":           lambda r: None,
    "build_text_content": lambda r: prose("company", r, [
        ("company name", "company_name"),
        ("crn",          "crn"),
        ("vat number",   "vat_number"),
        ("address",      "address"),
        ("email",        "email"),
        ("phone",        "phone"),
    ]),
    "company_id_strategy": "direct",
}


# ======= EMPLOYEES =======
ACCOUNT_REGISTRY["employees"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT *
        FROM employees
        WHERE is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Employee", r.get("first_name"), r.get("last_name")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("date_of_joining"),
    "build_text_content": lambda r: prose("employee", r, [
        ("first name",    "first_name"),
        ("last name",     "last_name"),
        ("email",         "email"),
        ("phone",         "phone"),
        ("nationality",   "nationality"),
        ("gender",        "gender"),
        ("status",        "status"),
        ("series number", "series_number"),
    ]),
    "company_id_strategy": "direct",
}


# ======= USER =======
ACCOUNT_REGISTRY["user"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT *
        FROM user
        WHERE is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "User", r.get("first_name"), r.get("last_name")
    ),
    "get_reference":      lambda r: r.get("email"),
    "get_status":         lambda r: None,
    "get_date":           lambda r: None,
    "build_text_content": lambda r: prose("user", r, [
        ("first name", "first_name"),
        ("last name",  "last_name"),
        ("email",      "email"),
        ("phone",      "phone"),
    ]),
    "company_id_strategy": "direct",
}


# ======= BUDGETS =======
ACCOUNT_REGISTRY["budgets"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT *
        FROM budgets
        WHERE is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Budget", r.get("budget_name"), r.get("budget_period")
    ),
    "get_reference":      lambda r: None,
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: None,
    "build_text_content": lambda r: prose("budget", r, [
        ("budget name",   "budget_name"),
        ("budget period", "budget_period"),
        ("status",        "status"),
    ]),
    "company_id_strategy": "direct",
}


# ======= EXPENSE REIMBURSEMENTS =======
ACCOUNT_REGISTRY["expense_reimbursements"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT er.*,
               CONCAT(e.first_name, ' ', COALESCE(e.last_name, '')) AS employee_name
        FROM expense_reimbursements er
        LEFT JOIN employees e ON e.id = er.employee_id
        WHERE er.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Expense Reimbursement", r.get("series_number"), r.get("employee_name")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: None,
    "get_date":           lambda r: r.get("transaction_date"),
    "get_amount":         extract_amount,
    "build_text_content": lambda r: prose("expense reimbursement", r, [
        ("series number",     "series_number"),
        ("employee",          "employee_name"),
        ("approval status",   "approval_status"),
        ("expense entry type","expense_entry_type"),
        ("paid by",           "paid_by"),
        ("description",       "description"),
    ]),
    "company_id_strategy": "direct",
}


# ======= CASH EXPENSES =======
ACCOUNT_REGISTRY["cash_expenses"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT ce.*,
               COALESCE(ce.company_id, p.company_id) AS company_id,
               COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS vendor_name
        FROM cash_expenses ce
        LEFT JOIN parties p ON p.id = ce.vendor_id
        WHERE ce.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Cash Expense", r.get("series_number"), r.get("vendor_name")
    ),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: None,
    "get_date":           lambda r: r.get("bill_date"),
    "get_amount":         extract_amount,
    "build_text_content": lambda r: prose("cash expense", r, [
        ("series number",  "series_number"),
        ("vendor",         "vendor_name"),
        ("approval status","approval_status"),
        ("narration",      "narration"),
    ]),
    "company_id_strategy": "direct",
}


# ======= ASSETS =======
ACCOUNT_REGISTRY["assets"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT *
        FROM assets
        WHERE is_deleted = 0
    """,
    "build_title":        lambda r: build_doc_title("Fixed Asset", r.get("asset_name")),
    "get_reference":      lambda r: r.get("series_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("acquisition_date") or r.get("posting_date"),
    "get_amount":         lambda r: r.get("asset_value"),
    "build_text_content": lambda r: prose("fixed asset", r, [
        ("asset name",          "asset_name"),
        ("series number",       "series_number"),
        ("status",              "status"),
        ("depreciation",        "depreciation"),
        ("asset specification", "asset_specification"),
    ]),
    "company_id_strategy": "direct",
}


# ======= ASSET TRANSFERS =======
ACCOUNT_REGISTRY["asset_transfers"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT at.*, a.asset_name,
               COALESCE(at.source_company_id, a.company_id) AS company_id
        FROM asset_transfers at
        LEFT JOIN assets a ON a.id = at.asset_id
        WHERE at.is_deleted = 0
    """,
    "build_title": lambda r: build_doc_title(
        "Asset Transfer", r.get("transfer_name"), r.get("asset_name")
    ),
    "get_reference":      lambda r: r.get("reference_number"),
    "get_status":         lambda r: r.get("status"),
    "get_date":           lambda r: r.get("transfer_date"),
    "build_text_content": lambda r: prose("asset transfer", r, [
        ("transfer name", "transfer_name"),
        ("asset name",    "asset_name"),
        ("status",        "status"),
        ("narration",     "narration"),
    ]),
    "company_id_strategy": "direct",
}

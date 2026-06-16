from __future__ import annotations

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str
    modules: list[str] | None = Field(
        default=None,
        description="Filter to specific modules, e.g. ['account', 'sales']. Omit to search all.",
    )
    status: list[str] | None = Field(
        default=None,
        description="Filter by status values, e.g. ['Paid', 'Partially Paid', 'Draft'].",
    )
    date_from: str | None = Field(
        default=None,
        description="Inclusive lower bound on document date (YYYY-MM-DD).",
    )
    date_to: str | None = Field(
        default=None,
        description="Inclusive upper bound on document date (YYYY-MM-DD).",
    )
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, description="Number of results to skip (for pagination).")


class SearchHit(BaseModel):
    id: str
    source_id: int
    doc_type: str
    module: str
    title: str
    reference: str | None = None
    status: str | None = None
    date: str | None = None
    amount: float | None = None
    score: float
    party_name: str | None = None
    company_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    approval_status: str | None = None
    transaction_type: str | None = None
    email: str | None = None
    phone: str | None = None
    highlight: dict[str, list[str]] | None = None
    # --- Invoice / payment ---
    payment_status: str | None = None
    due_date: str | None = None
    amount_paid: float | None = None
    amount_due: float | None = None
    supplier_invoice_number: str | None = None
    order_type: str | None = None
    payment_type: str | None = None
    payment_method_type: str | None = None
    cheque_number: str | None = None
    cheque_date: str | None = None
    is_reconciled: str | None = None
    narration: str | None = None
    ref_type: str | None = None
    party_role: str | None = None
    version: str | None = None
    po_number: str | None = None
    # --- Party / company profile ---
    party_type: str | None = None
    vat_number: str | None = None
    crn: str | None = None
    sales_lead_status: str | None = None
    sales_op_stage: str | None = None
    credit_hold: str | None = None
    is_active: str | None = None
    address: str | None = None
    date_of_joining: str | None = None
    nationality: str | None = None
    gender: str | None = None
    role_id: str | None = None
    # --- Reimbursement / expense ---
    budget_period: str | None = None
    transaction_date: str | None = None
    paid_by: str | None = None
    expense_entry_type: str | None = None
    bill_date: str | None = None
    # --- Assets ---
    asset_value: float | None = None
    acquisition_date: str | None = None
    depreciation: str | None = None
    asset_specification: str | None = None
    original_value: float | None = None
    # --- Sales order / fulfillment ---
    invoice_status: str | None = None
    delivery_status: str | None = None
    expiration_date: str | None = None
    return_status: str | None = None
    return_source: str | None = None
    stages: str | None = None
    expected_closing_date: str | None = None
    expected_revenue: float | None = None
    probability: float | None = None
    priority: str | None = None
    promotion_type: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    # --- Purchase fulfillment ---
    billing_status: str | None = None
    receiving_status: str | None = None
    rfq_type: str | None = None
    lead_time: str | None = None
    received_by: str | None = None
    agreement_type: str | None = None
    valid_up_to: str | None = None
    refund_status: str | None = None
    # --- Inventory / items ---
    item_type: str | None = None
    sales_price: float | None = None
    purchase_price: float | None = None
    upc_bar_code: str | None = None
    costing_method: str | None = None
    city: str | None = None
    summary: str | None = None
    transfer_type: str | None = None
    description: str | None = None
    # --- Manufacturing ---
    material_status: str | None = None
    production_start_date: str | None = None
    production_end_date: str | None = None
    quantity: float | None = None
    work_order_type: str | None = None
    # --- Equipment ---
    equipment_cost: float | None = None
    effective_date: str | None = None
    warranty_expiration_date: str | None = None
    maintenance_period: str | None = None
    # --- Gate register ---
    transporter_name: str | None = None
    driver_name: str | None = None
    driver_contact_number: str | None = None
    entry_datetime: str | None = None
    exit_datetime: str | None = None
    entry_purpose: str | None = None
    exit_purpose: str | None = None
    # --- Rental ---
    received_quantity: float | None = None
    returned_quantity: float | None = None
    # --- Drive ---
    file_extension: str | None = None
    mime_type: str | None = None
    drive_type: str | None = None
    is_private: str | None = None


class SearchResponse(BaseModel):
    results: list[SearchHit]
    total: int
    duration_ms: float


class SyncRequest(BaseModel):
    tables: list[str] | None = Field(
        default=None,
        description=(
            "List of table names to sync (e.g. ['assets', 'sales_invoices']). "
            "Omit or pass null to sync all tracked tables."
        ),
    )
    full_reindex: bool = Field(
        default=False,
        description=(
            "When true: deletes all existing OpenSearch documents for the target tables first, "
            "then re-indexes every row from MySQL. Use for first-time setup, after a registry "
            "change, or to recover a broken index. "
            "When false (default): upserts only — faster, but will not remove documents for rows "
            "that were hard-deleted from MySQL since the last sync."
        ),
    )
    recreate_indices: bool = Field(
        default=False,
        description=(
            "When true: drops and recreates the OpenSearch indices before syncing, "
            "rebuilding the vector mapping from the current config. "
            "Use when the embedding model dimension has changed (e.g. switching models). "
            "Implies full_reindex behaviour — all documents are re-indexed from scratch."
        ),
    )


class SyncResponse(BaseModel):
    indexed: int
    errors: int
    duration_ms: float


class SyncJobResponse(BaseModel):
    job_id: str
    status: str = "started"
    poll_url: str


class SyncJobStatus(BaseModel):
    job_id: str
    status: str          # "running" | "ok" | "partial" | "failed"
    indexed: int = 0
    errors: int = 0
    total_tables: int = 0
    completed_tables: int = 0
    failed_tables: list[str] = Field(default_factory=list)
    started_at: str
    completed_at: str | None = None
    duration_ms: float | None = None

"""Per-tenant registry overrides.

One module per tenant: `indexer/registry/tenants/<client_id>.py`, each exposing
an `OVERRIDES` dict. Tenants share the ~90% base registry; only their genuine
schema deltas live here. A tenant with no customizations needs no module (or an
empty `OVERRIDES = {}`).

Override grammar (see indexer/registry/overrides.py::apply_overrides):
    {"table": {"sql": "..."}}   merge — replace only the given keys, inherit rest
    {"table": None}             tenant lacks this table → drop it
    {"new_table": {full cfg}}   table unique to this tenant
"""

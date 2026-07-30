"""Registry overrides for tenant `vofxgf`."""

from __future__ import annotations

OVERRIDES: dict[str, dict | None] = {
    # Same schema as tenant `spar` (both run on the `spar_erpforce` database):
    # `sl_opportunity_parties` has no `company_id` column (it has party_id /
    # customer_id). The base SQL's `op.company_id` raises MySQL 1054 (Unknown
    # column). Derive company_id from the joined party instead.
    "sl_opportunity_parties": {
        "sql": """
            SELECT op.*,
                   p.company_id AS company_id,
                   COALESCE(NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)), ''), p.company_name, p.name) AS party_name
            FROM sl_opportunity_parties op
            LEFT JOIN parties p ON p.id = op.party_id
            WHERE op.is_deleted = 0
        """,
    },
}

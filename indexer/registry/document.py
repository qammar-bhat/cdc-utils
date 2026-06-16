"""Index registry — Document module (1 table)."""
from __future__ import annotations

from ._utils import build_doc_title, prose

INDEX = "erpforce_document"
MODULE = "document"

DOCUMENT_REGISTRY: dict[str, dict] = {}


# ======= DRIVE =======
DOCUMENT_REGISTRY["drive"] = {
    "index": INDEX, "module": MODULE,
    "sql": """
        SELECT d.*, d.title AS file_name, d.type AS drive_type, u.company_id
        FROM drive d
        LEFT JOIN `user` u ON u.id = d.created_by
        WHERE d.is_deleted = 0
    """,
    "build_title":        lambda r: build_doc_title("Document File", r.get("file_name")),
    "get_reference":      lambda r: None,
    "get_status":         lambda r: None,
    "get_date":           lambda r: None,
    "build_text_content": lambda r: prose("document file", r, [
        ("file name",      "file_name"),
        ("drive type",     "drive_type"),
        ("mime type",      "mime_type"),
        ("file extension", "file_extension"),
    ]),
    "company_id_strategy": "direct",
}

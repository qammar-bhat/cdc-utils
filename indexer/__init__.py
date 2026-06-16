"""erpforce-indexer — multi-tenant CDC/indexing service.

Owns the entire OpenSearch WRITE path for all clients: per-tenant index
creation, bulk sync, and CDC consumption. The hub is read-only on OpenSearch.
"""

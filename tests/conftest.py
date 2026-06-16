"""Test config — register two test tenants BEFORE any indexer module imports.

The tenant registry reads env at first access and caches a singleton, so the
env must be set here (import time) and the singleton reset if already loaded.
"""

from __future__ import annotations

import os
import sys

# Two tenants — same db name on purpose, distinct topic prefixes (the collision
# case the routing model must survive).
os.environ["TENANT_IDS"] = "spar,dev_env"

for cid, prefix in (("SPAR", "cdc_spar"), ("DEV_ENV", "cdc_dev_env")):
    os.environ.setdefault(f"{cid}_APPLICATION_DB_HOST", "127.0.0.1")
    os.environ.setdefault(f"{cid}_APPLICATION_DB_NAME", "shared_db")
    os.environ.setdefault(f"{cid}_APPLICATION_DB_USER", "test")
    os.environ.setdefault(f"{cid}_APPLICATION_DB_PASSWORD", "test")
    os.environ.setdefault(f"{cid}_CDC_TOPIC_PREFIX", prefix)

os.environ.setdefault("INDEXER_API_KEY", "test-indexer-key")
os.environ.setdefault("OPENSEARCH_HOST", "127.0.0.1")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")

# Reset the lazy tenant singleton if a prior import already loaded it.
if "indexer.tenants" in sys.modules:
    import indexer.tenants as _t
    _t._tenants = None

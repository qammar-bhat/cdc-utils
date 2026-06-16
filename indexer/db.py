"""Per-tenant read-only SQLAlchemy engines and safe query executor.

Multi-tenant: every query must name its client. The engine factory keeps one
connection pool per client, built from the tenant registry (src/tenants.py).

Security model — two independent layers per tenant:
  1. Each tenant's DB user has only SELECT privileges on their database.
  2. execute_safe_query() checks for forbidden SQL keywords before the
     query reaches the database — defence in depth.

client_id is a REQUIRED keyword argument: a call site that forgets it raises
TypeError immediately instead of silently querying another tenant's database.

All queries use SQLAlchemy text() with a bound params dict.
String interpolation of user input into SQL is never used.
"""

from __future__ import annotations

import re
import threading
import time

import logfire
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from indexer.tenants import get_tenant

# ---------------------------------------------------------------------------
# Per-tenant engine factory
# ---------------------------------------------------------------------------

# Hard ceiling on how long any single query may run (pymysql socket read/write
# timeout, seconds). A runaway query fails instead of hanging the request and
# holding its pooled connection forever.
_QUERY_TIMEOUT_S = 30

_engines: dict[str, Engine] = {}
_sessionmakers: dict[str, sessionmaker] = {}
# RLock, not Lock — get_sessionmaker calls get_engine while holding the lock,
# and a non-reentrant lock self-deadlocks on that path.
_lock = threading.RLock()  # CDC consumer thread + request threads both call this


def get_engine(client_id: str) -> Engine:
    """Return (and cache) the SQLAlchemy engine for a client's database."""
    engine = _engines.get(client_id)
    if engine is not None:
        return engine
    with _lock:
        engine = _engines.get(client_id)
        if engine is None:
            tenant = get_tenant(client_id)  # raises UnknownTenantError for bad ids
            engine = create_engine(
                tenant.db_url,
                pool_size=tenant.pool_size,
                max_overflow=tenant.max_overflow,
                pool_pre_ping=True,   # transparently reconnect on dropped connections
                pool_timeout=10,      # wait at most 10s for a free connection, then fail
                pool_recycle=3600,    # recycle connections older than 1h (avoid stale MySQL conns)
                # Per-connection caps so one slow query can't hang a request or hold a
                # pooled connection forever (connect timeout + server-side statement timeout).
                connect_args={
                    "connect_timeout": 10,
                    "read_timeout": _QUERY_TIMEOUT_S,
                    "write_timeout": _QUERY_TIMEOUT_S,
                },
            )
            _engines[client_id] = engine
            logfire.info("db engine created", client_id=client_id, db_name=tenant.db_name)
        return engine


def get_sessionmaker(client_id: str) -> sessionmaker:
    """Return (and cache) the session factory for a client's database."""
    sm = _sessionmakers.get(client_id)
    if sm is not None:
        return sm
    with _lock:
        sm = _sessionmakers.get(client_id)
        if sm is None:
            sm = sessionmaker(bind=get_engine(client_id), autocommit=False, autoflush=False)
            _sessionmakers[client_id] = sm
        return sm


# ---------------------------------------------------------------------------
# Keyword guard
# ---------------------------------------------------------------------------

_FORBIDDEN_KEYWORDS: frozenset[str] = frozenset({
    "insert", "update", "delete", "drop", "alter",
    "create", "truncate", "exec", "execute",
})

# Word-boundary pattern — prevents false positives like "update_date", "created_at", "exec_id"
_FORBIDDEN_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(_FORBIDDEN_KEYWORDS)) + r")\b",
    re.IGNORECASE,
)


def _check_for_forbidden_keywords(sql: str) -> None:
    """Raise ValueError if sql contains any write or DDL keyword.

    Uses word-boundary matching so column names like update_date or created_at
    are not falsely rejected. This guard runs before the query reaches the database.
    """
    match = _FORBIDDEN_PATTERN.search(sql)
    if match:
        keyword = match.group(1).lower()
        logfire.warning(
            "copilot db query rejected — forbidden keyword",
            keyword=keyword,
            sql_preview=sql[:200],
        )
        raise ValueError(
            f"Query rejected: forbidden keyword '{keyword}' detected. "
            "Only SELECT statements are permitted."
        )


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def execute_safe_query(sql: str, params: dict | None = None, *, client_id: str) -> list[dict]:
    """Execute a parameterised SELECT query on a client's database.

    Args:
        sql:       A SQL SELECT statement. Must not contain write or DDL keywords.
        params:    Optional dict of bind parameters (e.g. {"status": "active"}).
                   Always use params for user-supplied values — never interpolate.
        client_id: REQUIRED — which client's database to query. Keyword-only so
                   missing tenant context is a loud TypeError, never a silent
                   wrong-tenant query.

    Returns:
        A list of dicts, one per row. Empty list if the query returns no rows.

    Raises:
        ValueError: If the query contains forbidden SQL keywords.
        src.tenants.UnknownTenantError: If client_id is not registered.
        sqlalchemy.exc.SQLAlchemyError: On DB-level errors (bad column, timeout, etc.).
    """
    if params is None:
        params = {}

    _check_for_forbidden_keywords(sql)

    session_factory = get_sessionmaker(client_id)

    start = time.perf_counter()
    with session_factory() as session:
        result = session.execute(text(sql), params)
        rows = [dict(row._mapping) for row in result.fetchall()]

    duration_ms = (time.perf_counter() - start) * 1000
    # Low-level per-query trace — kept at debug so it doesn't drown the sync's
    # per-table progress logs. Raise LOG_LEVEL=DEBUG to see every SELECT.
    logfire.debug(
        "indexer db query executed",
        client_id=client_id,
        row_count=len(rows),
        duration_ms=round(duration_ms, 2),
        sql_preview=sql[:200],
    )

    return rows

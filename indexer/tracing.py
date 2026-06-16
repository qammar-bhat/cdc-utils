"""tracing.py — Logfire + Langfuse (OTel) wiring for the indexer.

Mirrors the hub's setup: Logfire is the primary APM (console + optional Logfire
cloud), and spans are ALSO exported to Langfuse via OTLP, tagged per tenant so a
single client's CDC/sync activity can be isolated in the shared project.

The indexer has no LangChain LLM calls, so there's no LangchainInstrumentor and
no LLM-span project — a single Langfuse project receives all spans.

Public API:
    build_langfuse_processors()  -> list[SpanProcessor]   (pass to logfire.configure)
    trace_context(client_id=..., service=...)             (stamps trace-level attrs)
"""

from __future__ import annotations

import base64
import contextvars
import json
import os
from contextlib import contextmanager

import logfire

# Langfuse OTel attribute keys. Import the canonical names if available; fall
# back to the stable string keys so a Langfuse version/skew can't break boot.
try:  # pragma: no cover - import shim
    from langfuse import LangfuseOtelSpanAttributes as _LF

    _USER_ID = _LF.TRACE_USER_ID
    _SESSION_ID = _LF.TRACE_SESSION_ID
    _TRACE_NAME = _LF.TRACE_NAME
    _TAGS = _LF.TRACE_TAGS
    _METADATA = _LF.TRACE_METADATA
except Exception:  # langfuse not installed / different version
    _USER_ID = "langfuse.user.id"
    _SESSION_ID = "langfuse.session.id"
    _TRACE_NAME = "langfuse.trace.name"
    _TAGS = "langfuse.trace.tags"
    _METADATA = "langfuse.trace.metadata"

_trace_ctx: contextvars.ContextVar[dict] = contextvars.ContextVar("_indexer_trace_ctx", default={})


class LangfuseAttributeInjector:
    """SpanProcessor that stamps trace-level Langfuse attrs onto every span from
    the per-task contextvars set by trace_context()."""

    def on_start(self, span, parent_context=None) -> None:
        attrs = _trace_ctx.get()
        if not attrs:
            return
        if attrs.get("session_id"):
            span.set_attribute(_SESSION_ID, attrs["session_id"])
        if attrs.get("trace_name"):
            span.set_attribute(_TRACE_NAME, attrs["trace_name"])
        if attrs.get("tags"):
            span.set_attribute(_TAGS, attrs["tags"])
        if attrs.get("metadata"):
            span.set_attribute(_METADATA, attrs["metadata"])

    def on_end(self, span) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True


def build_langfuse_processors() -> list:
    """Return span processors to hand to logfire.configure().

    Always includes the attribute injector. Adds a Langfuse OTLP exporter only
    when LANGFUSE_BASE_URL + keys are set — otherwise tracing-to-Langfuse is
    simply disabled (the service still runs and logs to console/Logfire).
    """
    processors: list = [LangfuseAttributeInjector()]

    base = os.environ.get("LANGFUSE_BASE_URL", "").rstrip("/")
    pub = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    sec = os.environ.get("LANGFUSE_SECRET_KEY", "")

    if base and pub and sec:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        auth = base64.b64encode(f"{pub}:{sec}".encode()).decode()
        exporter = OTLPSpanExporter(
            endpoint=f"{base}/api/public/otel/v1/traces",
            headers={"Authorization": f"Basic {auth}"},
        )
        processors.append(BatchSpanProcessor(exporter))
        logfire.info("Langfuse tracing enabled", base_url=base)
    else:
        logfire.warning("Langfuse not configured — span export to Langfuse disabled")

    return processors


@contextmanager
def trace_context(*, client_id: str | None = None, service: str, session_id: str | None = None, **extra):
    """Stamp per-task trace attributes so all spans created within carry them.

    `client_id` (tenant) is added as both a `client:{id}` tag (first-class
    Langfuse filter) and metadata, so one tenant's traces are isolable in the
    shared project.
    """
    metadata: dict[str, str] = {"service": service}
    if client_id:
        metadata["client_id"] = client_id
    metadata.update({k: str(v)[:200] for k, v in extra.items()})

    tags = [service]
    if client_id:
        tags.append(f"client:{client_id}")

    token = _trace_ctx.set({
        "session_id": session_id or "",
        "trace_name": service,
        "tags": tags,
        "metadata": json.dumps(metadata),
    })
    try:
        yield
    finally:
        _trace_ctx.reset(token)

"""Redis Streams CDC consumer — reads from Debezium Server Redis Streams sink."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import defaultdict

import logfire

logger = logging.getLogger(__name__)

_GROUP_NAME        = "smart-search-cdc"
_CONSUMER_NAME     = "worker-1"
_BATCH_SIZE        = 50
# Block time doubles as redis-py's client-side read deadline for blocking
# stream commands — too small (50ms) and a momentarily slow Redis raises
# TimeoutError on every read. 2s keeps CDC latency low while polling Redis
# 40x less and tolerating load spikes.
_BLOCK_MS          = 2000
_RECONNECT_DELAY_S = 5
_MAX_RETRIES       = 5
_DLQ_STREAM        = "cdc:dead-letter"
_LAG_WARN_THRESHOLD = 1000   # warn if any stream has more than this many unprocessed messages
_LAG_CHECK_EVERY    = 500    # check stream depth every N iterations (N tenants × 45 streams)
_PENDING_CHECK_EVERY = 100   # check for unacked pending messages every N iterations (not every loop)


def _make_redis_client():
    """Build a CDC Redis client hardened against Docker's embedded-DNS flakiness.

    Under heavy load (e.g. a full reindex hammering the box) the Docker DNS
    resolver (127.0.0.11) sporadically drops lookups, surfacing as
    "Temporary failure in name resolution". redis-py does NOT retry these by
    default, so a single blip would otherwise kill a consumer loop iteration.

    socket_keepalive keeps the connection warm (fewer reconnects → fewer DNS
    lookups); the retry transparently re-attempts ConnectionErrors (which is how
    redis-py wraps the DNS gaierror) with backoff. TimeoutError is deliberately
    NOT retried here — the blocking XREADGROUP read deadline is expected and is
    handled by the loop.
    """
    import redis
    from redis.backoff import ExponentialBackoff
    from redis.retry import Retry

    from indexer.config import settings

    return redis.from_url(
        settings.redis_url,
        decode_responses=True,
        protocol=2,
        socket_keepalive=True,
        socket_connect_timeout=5,
        health_check_interval=30,
        retry=Retry(ExponentialBackoff(cap=3.0, base=0.2), retries=5),
        retry_on_error=[redis.exceptions.ConnectionError],
    )


def _build_stream_map() -> dict[str, str]:
    """stream key → client_id, for every tenant and tracked table.

    Each client's Debezium Server is configured with topic.prefix=cdc_{client_id},
    so the Redis stream key is {topic_prefix}.{db_name}.{table}. The prefix — not
    the db name — identifies the tenant (db names collide across clients).
    """
    from indexer.registry.overrides import resolve_registry
    from indexer.tenants import all_tenants

    return {
        f"{t.cdc_topic_prefix}.{t.db_name}.{table}": t.client_id
        for t in all_tenants()
        for table in resolve_registry(t.client_id)
    }


class CDCConsumer:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="cdc-consumer")
        self._thread.start()
        logfire.info("indexer CDC consumer starting")

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        logfire.info("indexer CDC consumer stopped")

    def _run(self) -> None:
        """Supervisor — keeps a consumer session alive across ANY failure,
        INCLUDING setup failures (e.g. Redis unreachable at boot), until stop is
        signalled. Without this, an exception before the inner loop (building the
        client, creating consumer groups) would kill the thread permanently with
        no auto-recovery, silently stopping all CDC."""
        while not self._stop.is_set():
            try:
                self._run_session()
            except Exception:
                logfire.exception(
                    "CDC consumer session crashed — restarting", delay_s=_RECONNECT_DELAY_S
                )
                self._stop.wait(_RECONNECT_DELAY_S)

    def _run_session(self) -> None:
        import redis

        r = _make_redis_client()
        stream_to_tenant = _build_stream_map()
        streams = list(stream_to_tenant)

        for stream in streams:
            try:
                r.xgroup_create(stream, _GROUP_NAME, id="$", mkstream=True)
            except redis.exceptions.ResponseError:
                pass  # group already exists

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        iteration = 0
        try:
            while not self._stop.is_set():
                iteration += 1
                if iteration % _LAG_CHECK_EVERY == 0:
                    try:
                        for stream in streams:
                            depth = r.xlen(stream)
                            if depth > _LAG_WARN_THRESHOLD:
                                logfire.warning(
                                    "indexer CDC stream backlog high",
                                    stream=stream,
                                    depth=depth,
                                    threshold=_LAG_WARN_THRESHOLD,
                                )
                    except redis.exceptions.RedisError:
                        # A blip here (e.g. a momentary connection error) is not
                        # worth crashing the whole session over — the depth check
                        # is diagnostic only, not on the critical read/dispatch path.
                        logfire.warning("CDC lag check failed — skipping this round")
                try:
                    # Drain pending (unacknowledged) messages from a previous crash
                    # Only check every _PENDING_CHECK_EVERY iterations to avoid 45+ Redis
                    # calls on every tight loop iteration in the normal (no-pending) case.
                    pending_events: list[dict] = []
                    pending_by_stream: dict[str, list[str]] = defaultdict(list)
                    skip_pending = (iteration % _PENDING_CHECK_EVERY != 0)

                    for stream in streams:
                        if skip_pending:
                            break
                        pending = r.xpending_range(stream, _GROUP_NAME, "-", "+", _BATCH_SIZE)
                        if not pending:
                            continue

                        dlq_ids  = [p["message_id"] for p in pending if p["times_delivered"] >= _MAX_RETRIES]
                        live_ids = [p["message_id"] for p in pending if p["times_delivered"] < _MAX_RETRIES]

                        if dlq_ids:
                            dead = r.xclaim(stream, _GROUP_NAME, _CONSUMER_NAME, 0, dlq_ids)
                            for msg_id, fields in dead:
                                r.xadd(_DLQ_STREAM, {
                                    "value":       next(iter(fields.values()), "") if fields else "",
                                    "original_id": msg_id,
                                    "stream":      stream,
                                    "reason":      "max_retries_exceeded",
                                })
                                logfire.error(f"indexer CDC dead-letter id={msg_id} stream={stream}")
                            r.xack(stream, _GROUP_NAME, *dlq_ids)

                        if live_ids:
                            reclaimed = r.xclaim(stream, _GROUP_NAME, _CONSUMER_NAME, 0, live_ids)
                            if reclaimed:
                                events, ids = _parse_messages(reclaimed, stream_to_tenant[stream])
                                pending_events.extend(events)
                                pending_by_stream[stream].extend(ids)

                    if pending_events:
                        loop.run_until_complete(self._dispatch(pending_events))
                    for stream, ids in pending_by_stream.items():
                        if ids:
                            r.xack(stream, _GROUP_NAME, *ids)
                    if pending_events or pending_by_stream:
                        continue  # re-check pending before reading new

                    # Read new messages from all tracked streams
                    results = r.xreadgroup(
                        _GROUP_NAME, _CONSUMER_NAME,
                        {s: ">" for s in streams},
                        count=_BATCH_SIZE,
                        block=_BLOCK_MS,
                    )
                    if not results:
                        continue

                    all_events: list[dict] = []
                    by_stream: dict[str, list[str]] = defaultdict(list)
                    for stream_name, messages in results:
                        events, ids = _parse_messages(messages, stream_to_tenant[stream_name])
                        all_events.extend(events)
                        by_stream[stream_name].extend(ids)

                    if all_events:
                        loop.run_until_complete(self._dispatch(all_events))
                    for stream_name, ids in by_stream.items():
                        if ids:
                            r.xack(stream_name, _GROUP_NAME, *ids)

                except redis.exceptions.TimeoutError:
                    # A read deadline lapsing on a blocking XREADGROUP just means
                    # "no events yet / Redis momentarily slow" — not an error.
                    # Loop again immediately; no traceback, no penalty sleep.
                    logger.debug("CDC read timed out (no events / slow redis) — continuing")
                except Exception:
                    logfire.exception(
                        "CDC consumer error — retrying", delay_s=_RECONNECT_DELAY_S
                    )
                    time.sleep(_RECONNECT_DELAY_S)
                    # Rebuild the client so a poisoned connection pool (stale
                    # sockets, DNS that resolved mid-flight) can't wedge the loop.
                    try:
                        r.close()
                    except Exception:
                        pass
                    r = _make_redis_client()
        finally:
            loop.close()

    async def _dispatch(self, events: list[dict]) -> None:
        from indexer.cdc_handler import ingest_change_events_batch
        from indexer.tracing import trace_context

        # A batch can mix tenants; tag with the single client when uniform so
        # Langfuse can filter, else just the cdc service.
        clients = {e.get("client_id") for e in events}
        cid = next(iter(clients)) if len(clients) == 1 else None
        with trace_context(client_id=cid, service="indexer-cdc"):
            await ingest_change_events_batch(events)


def _parse_messages(messages: list, client_id: str) -> tuple[list[dict], list[str]]:
    """Parse Debezium Redis sink stream entries into CDC events, stamped with the tenant."""
    events: list[dict] = []
    msg_ids: list[str] = []

    for msg_id, fields in messages:
        # Debezium Redis sink uses the serialized record key as the field name
        # and the event JSON as its value — there is no fixed "value" field name.
        raw = next(iter(fields.values()), "") if fields else ""
        if not raw:
            logger.warning("CDC: empty message id=%s — skipped, ACK'd", msg_id)
            msg_ids.append(msg_id)
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("CDC: non-JSON message id=%s — skipped, ACK'd", msg_id)
            msg_ids.append(msg_id)
            continue

        # With schemas disabled the payload is the event directly;
        # with schemas enabled it's wrapped under a "payload" key.
        event = payload.get("payload", payload)
        table = event.get("source", {}).get("table", "")
        op    = event.get("op", "c")

        if not table:
            logger.warning("CDC: no table in message id=%s — skipped, ACK'd", msg_id)
            msg_ids.append(msg_id)
            continue

        events.append({
            "op":        op,
            "client_id": client_id,
            "source":    {"table": table},
            "before":    event.get("before"),
            "after":     event.get("after"),
        })
        msg_ids.append(msg_id)

    return events, msg_ids


cdc_consumer = CDCConsumer()

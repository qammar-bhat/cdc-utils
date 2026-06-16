"""config.py — service configuration for the erpforce-indexer.

A trimmed subset of the hub's src/config.py: only what the WRITE path needs.

  - Settings.redis_url                 (Redis Streams CDC + sync job status)
  - Settings.resolve_embedding_runtime (embedding profile from llm_profiles.json)
  - os_settings                        (OpenSearch connection — folded in from the
                                        hub's src/smart_search/config.py)
  - get_redis()                        (async Redis singleton for sync job status)

LOCK-STEP CONTRACT #1: the embedding profile (model + dimension) MUST match the
hub's llm_profiles.json exactly. A mismatch silently breaks kNN search because
the vectors live in different spaces. Both services log (model, dimension) at
startup.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import logfire
import redis.asyncio as aioredis
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# OpenSearch connection (folded in from hub src/smart_search/config.py)
# ---------------------------------------------------------------------------

@dataclass
class OpenSearchSettings:
    host: str = ""
    port: int = 9200
    username: str = "admin"
    password: str = ""
    verify_certs: bool = False

    def __post_init__(self) -> None:
        self.host = os.environ.get("OPENSEARCH_HOST", "opensearch")
        self.port = int(os.environ.get("OPENSEARCH_PORT", "9200"))
        self.username = os.environ.get("OPENSEARCH_USERNAME", "admin")
        self.password = os.environ.get("OPENSEARCH_PASSWORD", "")
        # False in dev (self-signed cert), True in prod (CA-signed cert)
        self.verify_certs = os.environ.get("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true"


os_settings = OpenSearchSettings()


# ---------------------------------------------------------------------------
# llm_profiles.json loader (embedding profiles only)
# ---------------------------------------------------------------------------

_cached_config: dict[str, Any] | None = None
_cached_mtime: float = 0.0


def _load_llm_config(config_path: Path) -> dict[str, Any]:
    """Load and cache llm_profiles.json; re-reads only when mtime changes."""
    global _cached_config, _cached_mtime
    try:
        mtime = config_path.stat().st_mtime
    except OSError as exc:
        logfire.warning(
            "Failed to stat llm_profiles.json — falling back to default embedding profile",
            config_path=str(config_path),
            error=str(exc),
        )
        return {}
    if _cached_config is not None and mtime == _cached_mtime:
        return _cached_config
    try:
        result = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logfire.warning(
            "llm_profiles.json missing or malformed — falling back to default embedding profile",
            config_path=str(config_path),
            error=str(exc),
        )
        return {}
    _cached_config = result
    _cached_mtime = mtime
    return _cached_config


class Settings:
    def __init__(self) -> None:
        self.config_path = Path(os.environ.get("LLM_CONFIG_PATH", "llm_profiles.json"))
        self.log_level: str = os.environ.get("LOG_LEVEL", "INFO")
        self.redis_url: str = os.environ.get("REDIS_URL", "redis://redis:6379/0")

    def resolve_embedding_runtime(self) -> dict[str, Any]:
        """Return embedding runtime settings from the active embedding_profile in
        llm_profiles.json. Supports bedrock (Titan), fastembed (local ONNX), openai.
        Falls back to fastembed mxbai-embed-large-v1 if config is missing.
        """
        _EMBEDDING_FALLBACK: dict[str, Any] = {
            "provider": "fastembed",
            "model": "mixedbread-ai/mxbai-embed-large-v1",
            "region": "us-east-1",
            "api_base": "",
            "api_key_env": "",
            "dimension": 1024,
        }

        config = _load_llm_config(self.config_path)
        embedding_profiles = config.get("embedding_profiles", {}) if isinstance(config, dict) else {}
        profile_name = config.get("embedding_profile", "fastembed_default") if isinstance(config, dict) else "fastembed_default"

        profile = embedding_profiles.get(profile_name, {}) if isinstance(embedding_profiles, dict) else {}
        if not isinstance(profile, dict):
            profile = {}

        if not profile:
            logfire.warning(
                "Embedding profile not found — falling back to fastembed default",
                requested_profile=profile_name,
            )

        merged = {**_EMBEDDING_FALLBACK, **profile}

        api_key_env = str(merged.get("api_key_env", ""))
        api_key = os.environ.get(api_key_env, "") if api_key_env else ""

        return {
            "profile": profile_name,
            "provider": str(merged.get("provider", "fastembed")),
            "model": str(merged.get("model", _EMBEDDING_FALLBACK["model"])),
            "api_key": api_key,
            "api_base": str(merged.get("api_base", "")),
            "region": str(merged.get("region", "us-east-1")),
            "dimension": int(merged.get("dimension", 1024)),
        }


settings = Settings()


# ---------------------------------------------------------------------------
# Async Redis singleton (sync job status; mirrors hub redis_client.py)
# ---------------------------------------------------------------------------

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Return the shared async Redis client, creating it on first call."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True, protocol=2)
    return _redis

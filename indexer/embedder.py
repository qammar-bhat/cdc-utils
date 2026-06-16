from __future__ import annotations

import asyncio
from functools import cached_property

import logfire

from indexer.config import settings


class EmbeddingService:
    """Wraps embedding providers based on the active embedding_profile in llm_profiles.json.

    Supported providers: bedrock (Titan), fastembed (local ONNX), openai.
    Model is loaded once on first use.
    """

    @cached_property
    def _model(self):
        runtime = settings.resolve_embedding_runtime()
        provider = runtime["provider"]
        model_name = runtime["model"]

        logfire.info("Loading embedding model", provider=provider, model=model_name)

        if provider == "bedrock":
            import boto3
            from botocore.config import Config

            region = runtime.get("region", "us-east-1")
            # adaptive retry mode backs off automatically on Bedrock throttling,
            # which matters once embed calls run in parallel
            client = boto3.client(
                "bedrock-runtime",
                region_name=region,
                config=Config(retries={"max_attempts": 5, "mode": "adaptive"}),
            )

            class _BedrockWrapper:
                """Titan embed models accept ONE text per invoke_model call.
                Batches are fanned out over a thread pool — sequential calls made
                bulk indexing unusably slow (50-row batch = 50 round trips).
                boto3 clients are thread-safe; sharing one across workers is fine.
                """

                _MAX_WORKERS = 8
                _MAX_CHARS = 25000  # Titan G1 input cap is 8192 tokens — stay under it

                def __init__(self, client, model_id):
                    self._client = client
                    self._model_id = model_id

                def _embed_one(self, text: str) -> list[float]:
                    import json
                    body = json.dumps({"inputText": text[: self._MAX_CHARS]})
                    resp = self._client.invoke_model(
                        modelId=self._model_id,
                        body=body,
                        contentType="application/json",
                        accept="application/json",
                    )
                    return json.loads(resp["body"].read())["embedding"]

                def embed_documents(self, texts: list[str]) -> list[list[float]]:
                    if len(texts) == 1:
                        return [self._embed_one(texts[0])]
                    from concurrent.futures import ThreadPoolExecutor
                    with ThreadPoolExecutor(max_workers=self._MAX_WORKERS) as pool:
                        return list(pool.map(self._embed_one, texts))

            return _BedrockWrapper(client, model_name)

        if provider == "fastembed":
            from fastembed import TextEmbedding

            _fe = TextEmbedding(model_name=model_name)

            class _FastEmbedWrapper:
                def embed_documents(self, texts: list[str]) -> list[list[float]]:
                    return [v.tolist() for v in _fe.embed(texts)]

            return _FastEmbedWrapper()

        if provider == "openai":
            from langchain_openai import OpenAIEmbeddings
            return OpenAIEmbeddings(
                model=model_name,
                openai_api_key=runtime["api_key"],
                openai_api_base=runtime["api_base"] or None,
            )

        raise ValueError(f"Unsupported embedding provider: {provider!r}. Use 'bedrock', 'fastembed', or 'openai'.")

    async def embed(self, text: str) -> list[float]:
        """Embed a single string and return the float vector."""
        loop = asyncio.get_running_loop()
        vectors = await loop.run_in_executor(None, self._model.embed_documents, [text])
        return vectors[0]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of strings. More efficient than calling embed() in a loop."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._model.embed_documents, texts)


embedder = EmbeddingService()

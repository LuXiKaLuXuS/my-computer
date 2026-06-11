from __future__ import annotations

import asyncio
import hashlib
from functools import lru_cache

import httpx

from app.config import get_settings
from app.logging_config import get_logger
from app.models.memory import EMBEDDING_DIMENSION

logger = get_logger(__name__)
settings = get_settings()


def _hash_embedding(text: str) -> list[float]:
    digest = hashlib.sha384(text.encode()).digest()
    values = [b / 255.0 for b in digest[:EMBEDDING_DIMENSION]]
    if len(values) < EMBEDDING_DIMENSION:
        values.extend([0.0] * (EMBEDDING_DIMENSION - len(values)))
    return values[:EMBEDDING_DIMENSION]


def _normalize_dimension(values: list[float]) -> list[float]:
    if len(values) > EMBEDDING_DIMENSION:
        return values[:EMBEDDING_DIMENSION]
    if len(values) < EMBEDDING_DIMENSION:
        return values + [0.0] * (EMBEDDING_DIMENSION - len(values))
    return values


class EmbeddingService:
    """Unified embedding service for pgvector JSONB + ChromaDB."""

    def __init__(self) -> None:
        self._model = None
        self._provider = self._resolve_provider()
        logger.info("embedding_provider_init", provider=self._provider, model=settings.embedding_model)

    def _resolve_provider(self) -> str:
        preferred = (settings.embedding_provider or "sentence-transformers").lower()
        if preferred == "sentence-transformers":
            try:
                import sentence_transformers  # noqa: F401

                return "sentence-transformers"
            except ImportError:
                logger.warning("sentence_transformers_not_installed", fallback="hash")
                return "hash"
        if preferred == "openai" and settings.openai_api_key:
            return "openai"
        if preferred == "hash":
            return "hash"
        return preferred

    def _load_sentence_transformer(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(settings.embedding_model)
        return self._model

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def dimension(self) -> int:
        return EMBEDDING_DIMENSION

    async def embed(self, text: str) -> list[float]:
        if self._provider == "openai" and settings.openai_api_key:
            return await self._openai_embed(text)
        if self._provider == "sentence-transformers":
            return await asyncio.to_thread(self._st_embed, text)
        return _hash_embedding(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self._provider == "sentence-transformers":
            return await asyncio.to_thread(self._st_embed_batch, texts)
        return [await self.embed(t) for t in texts]

    def _st_embed(self, text: str) -> list[float]:
        model = self._load_sentence_transformer()
        vector = model.encode(text, normalize_embeddings=True)
        return _normalize_dimension(vector.tolist())

    def _st_embed_batch(self, texts: list[str]) -> list[list[float]]:
        model = self._load_sentence_transformer()
        vectors = model.encode(texts, normalize_embeddings=True)
        return [_normalize_dimension(v.tolist()) for v in vectors]

    async def _openai_embed(self, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={"model": "text-embedding-3-small", "input": text},
            )
            resp.raise_for_status()
            data = resp.json()
            return _normalize_dimension(data["data"][0]["embedding"])


@lru_cache
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()
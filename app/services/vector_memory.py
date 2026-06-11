import asyncio
import uuid
from typing import Any

import chromadb
from chromadb.api import ClientAPI
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings
from app.logging_config import get_logger
from app.services.embeddings import get_embedding_service

logger = get_logger(__name__)
settings = get_settings()


class VectorMemory:
    """ChromaDB-backed per-user vector memory with unified embeddings."""

    def __init__(self) -> None:
        self._client: ClientAPI | None = None
        self._remote = False

    def _get_client(self) -> ClientAPI:
        if self._client is None:
            try:
                self._client = chromadb.HttpClient(
                    host=settings.chroma_host,
                    port=settings.chroma_port,
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
                self._client.heartbeat()
                self._remote = True
            except Exception as exc:
                logger.warning("chroma_unavailable", error=str(exc))
                self._client = chromadb.PersistentClient(
                    path=str(settings.chroma_persist_dir) if hasattr(settings, "chroma_persist_dir") else "/home/lukpak/my-computer/.data/chroma",
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
                self._remote = False
        return self._client

    def _collection_name(self, user_id: str) -> str:
        return f"{settings.chroma_collection_prefix}_{user_id}"

    def _get_collection(self, user_id: str):
        client = self._get_client()
        return client.get_or_create_collection(
            self._collection_name(user_id),
            metadata={"hnsw:space": "cosine"},
        )

    def is_available(self) -> bool:
        try:
            self._get_client()
            return True
        except Exception:
            return False

    def is_remote(self) -> bool:
        self._get_client()
        return self._remote

    async def add(
        self,
        user_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        doc_id: str | None = None,
    ) -> str:
        service = get_embedding_service()
        embedding = await service.embed(content)
        collection = self._get_collection(user_id)
        doc_id = doc_id or str(uuid.uuid4())
        await asyncio.to_thread(
            collection.add,
            documents=[content],
            embeddings=[embedding],
            ids=[doc_id],
            metadatas=[metadata or {}],
        )
        return doc_id

    async def search(self, user_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        service = get_embedding_service()
        query_embedding = await service.embed(query)
        collection = self._get_collection(user_id)
        count = await asyncio.to_thread(collection.count)
        if count == 0:
            return []
        results = await asyncio.to_thread(
            collection.query,
            query_embeddings=[query_embedding],
            n_results=min(limit, count),
        )
        items: list[dict[str, Any]] = []
        for i, doc in enumerate(results.get("documents", [[]])[0]):
            items.append(
                {
                    "content": doc,
                    "metadata": results.get("metadatas", [[]])[0][i] if results.get("metadatas") else {},
                    "distance": results.get("distances", [[]])[0][i] if results.get("distances") else None,
                }
            )
        return items


vector_memory = VectorMemory()
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import DBMemoryItem
from app.services.embeddings import get_embedding_service


class EpisodicMemoryService:
    def __init__(self) -> None:
        self._embeddings = get_embedding_service()

    async def save_step(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        goal_id: uuid.UUID | None,
        step_type: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> DBMemoryItem:
        embedding = await self._embeddings.embed(content)
        item = DBMemoryItem(
            user_id=user_id,
            goal_id=goal_id,
            step_type=step_type,
            content=content,
            metadata_=metadata,
            embedding=embedding,
        )
        db.add(item)
        await db.flush()
        return item

    async def get_timeline(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        goal_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[DBMemoryItem], int]:
        query = select(DBMemoryItem).where(DBMemoryItem.user_id == user_id)
        count_query = select(func.count()).select_from(DBMemoryItem).where(DBMemoryItem.user_id == user_id)

        if goal_id:
            query = query.where(DBMemoryItem.goal_id == goal_id)
            count_query = count_query.where(DBMemoryItem.goal_id == goal_id)

        query = query.order_by(DBMemoryItem.created_at.desc()).limit(limit).offset(offset)

        items = list((await db.execute(query)).scalars().all())
        total = (await db.execute(count_query)).scalar_one()
        return items, total


episodic_memory = EpisodicMemoryService()
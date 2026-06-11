import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.auth import get_current_active_user
from app.models.user import DBUser
from app.schemas.memory import MemoryTimelineItem, MemoryTimelineResponse
from app.services.episodic_memory import episodic_memory

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/timeline", response_model=MemoryTimelineResponse)
async def memory_timeline(
    goal_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryTimelineResponse:
    items, total = await episodic_memory.get_timeline(
        db,
        user_id=current_user.id,
        goal_id=goal_id,
        limit=limit,
        offset=offset,
    )
    return MemoryTimelineResponse(
        items=[
            MemoryTimelineItem(
                id=item.id,
                goal_id=item.goal_id,
                step_type=item.step_type,
                content=item.content,
                metadata=item.metadata_,
                created_at=item.created_at,
            )
            for item in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
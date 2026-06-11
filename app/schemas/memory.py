import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class MemoryTimelineItem(BaseModel):
    id: uuid.UUID
    goal_id: uuid.UUID | None
    step_type: str
    content: str
    metadata: dict[str, Any] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MemoryTimelineResponse(BaseModel):
    items: list[MemoryTimelineItem]
    total: int
    limit: int
    offset: int
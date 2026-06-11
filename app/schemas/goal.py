import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    mode: str = Field(default="ensemble", pattern="^(ensemble|single|parallel)$")
    project_id: uuid.UUID | None = None


class GoalRunRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=5000)
    mode: str = Field(default="ensemble", pattern="^(ensemble|single|parallel)$")
    project_id: uuid.UUID | None = None


class GoalResponse(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    status: str
    mode: str
    result: dict[str, Any] | None
    tokens_used: int
    project_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}
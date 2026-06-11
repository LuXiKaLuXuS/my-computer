import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.project import ProjectPermission


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class ProjectShareRequest(BaseModel):
    user_id: uuid.UUID
    permission: ProjectPermission = ProjectPermission.VIEW


class ProjectMemberAdd(BaseModel):
    email: str
    permission: ProjectPermission = ProjectPermission.VIEW


class ProjectMemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    username: str
    email: str
    permission: ProjectPermission
    created_at: datetime


class ProjectResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    members: list[ProjectMemberResponse] = []

    model_config = {"from_attributes": True}
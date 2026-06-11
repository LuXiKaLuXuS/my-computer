import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DBUser(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    api_keys: Mapped[list["DBApiKey"]] = relationship(
        "DBApiKey", back_populates="user", cascade="all, delete-orphan"
    )
    goals: Mapped[list["DBGoal"]] = relationship(
        "DBGoal", back_populates="user", cascade="all, delete-orphan"
    )
    memory_items: Mapped[list["DBMemoryItem"]] = relationship(
        "DBMemoryItem", back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["DBRefreshToken"]] = relationship(
        "DBRefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    owned_projects: Mapped[list["DBProject"]] = relationship(
        "DBProject", back_populates="owner", cascade="all, delete-orphan"
    )
    project_memberships: Mapped[list["DBProjectMember"]] = relationship(
        "DBProjectMember", back_populates="user", cascade="all, delete-orphan"
    )


from app.models.api_key import DBApiKey  # noqa: E402
from app.models.goal import DBGoal  # noqa: E402
from app.models.memory import DBMemoryItem  # noqa: E402
from app.models.project import DBProject, DBProjectMember  # noqa: E402
from app.models.refresh_token import DBRefreshToken  # noqa: E402
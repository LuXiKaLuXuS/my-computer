import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ProjectPermission(str, enum.Enum):
    VIEW = "view"
    EDIT = "edit"
    ADMIN = "admin"


class DBProject(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    owner: Mapped["DBUser"] = relationship("DBUser", back_populates="owned_projects")
    members: Mapped[list["DBProjectMember"]] = relationship(
        "DBProjectMember", back_populates="project", cascade="all, delete-orphan"
    )
    goals: Mapped[list["DBGoal"]] = relationship("DBGoal", back_populates="project")


class DBProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    permission: Mapped[ProjectPermission] = mapped_column(
        Enum(ProjectPermission, name="project_permission", values_callable=lambda x: [e.value for e in x]),
        default=ProjectPermission.VIEW,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped["DBProject"] = relationship("DBProject", back_populates="members")
    user: Mapped["DBUser"] = relationship("DBUser", back_populates="project_memberships")


from app.models.goal import DBGoal  # noqa: E402
from app.models.user import DBUser  # noqa: E402
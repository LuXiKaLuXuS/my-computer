import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies.auth import get_current_active_user
from app.models.project import DBProject, DBProjectMember, ProjectPermission
from app.models.user import DBUser
from app.schemas.project import (
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberResponse,
    ProjectResponse,
    ProjectShareRequest,
)

router = APIRouter(prefix="/projects", tags=["projects"])

PERMISSION_RANK = {
    ProjectPermission.VIEW: 1,
    ProjectPermission.EDIT: 2,
    ProjectPermission.ADMIN: 3,
}


def _build_project_response(project: DBProject) -> ProjectResponse:
    members = [
        ProjectMemberResponse(
            id=m.id,
            user_id=m.user_id,
            username=m.user.username,
            email=m.user.email,
            permission=m.permission,
            created_at=m.created_at,
        )
        for m in project.members
    ]
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        owner_id=project.owner_id,
        created_at=project.created_at,
        updated_at=project.updated_at,
        members=members,
    )


async def _get_project_with_access(
    project_id: uuid.UUID,
    user: DBUser,
    db: AsyncSession,
    min_permission: ProjectPermission = ProjectPermission.VIEW,
) -> DBProject:
    result = await db.execute(
        select(DBProject)
        .options(selectinload(DBProject.members).selectinload(DBProjectMember.user))
        .where(DBProject.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    if project.owner_id == user.id:
        return project

    membership = next((m for m in project.members if m.user_id == user.id), None)
    if not membership or PERMISSION_RANK[membership.permission] < PERMISSION_RANK[min_permission]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    return project


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    project = DBProject(
        owner_id=current_user.id,
        name=payload.name,
        description=payload.description,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project, ["members"])
    return _build_project_response(project)


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectResponse]:
    result = await db.execute(
        select(DBProject)
        .options(selectinload(DBProject.members).selectinload(DBProjectMember.user))
        .where(
            or_(
                DBProject.owner_id == current_user.id,
                DBProject.members.any(DBProjectMember.user_id == current_user.id),
            )
        )
        .order_by(DBProject.updated_at.desc())
    )
    return [_build_project_response(p) for p in result.scalars().all()]


@router.get("/shared", response_model=list[ProjectResponse])
async def list_shared_projects(
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectResponse]:
    result = await db.execute(
        select(DBProject)
        .options(selectinload(DBProject.members).selectinload(DBProjectMember.user))
        .join(DBProjectMember, DBProjectMember.project_id == DBProject.id)
        .where(
            DBProjectMember.user_id == current_user.id,
            DBProject.owner_id != current_user.id,
        )
        .order_by(DBProject.updated_at.desc())
    )
    return [_build_project_response(p) for p in result.scalars().all()]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID,
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    project = await _get_project_with_access(project_id, current_user, db)
    return _build_project_response(project)


@router.post("/{project_id}/share", response_model=ProjectMemberResponse)
async def share_project(
    project_id: uuid.UUID,
    payload: ProjectShareRequest,
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectMemberResponse:
    project = await _get_project_with_access(
        project_id, current_user, db, min_permission=ProjectPermission.ADMIN
    )
    if payload.user_id == project.owner_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Owner is already a member")

    user_result = await db.execute(select(DBUser).where(DBUser.id == payload.user_id))
    target_user = user_result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    existing = await db.execute(
        select(DBProjectMember).where(
            DBProjectMember.project_id == project_id,
            DBProjectMember.user_id == payload.user_id,
        )
    )
    member = existing.scalar_one_or_none()
    if member:
        member.permission = payload.permission
    else:
        member = DBProjectMember(
            project_id=project_id,
            user_id=payload.user_id,
            permission=payload.permission,
        )
        db.add(member)
    await db.flush()
    await db.refresh(member, ["user"])

    return ProjectMemberResponse(
        id=member.id,
        user_id=member.user_id,
        username=member.user.username,
        email=member.user.email,
        permission=member.permission,
        created_at=member.created_at,
    )


@router.post("/{project_id}/members", response_model=ProjectMemberResponse)
async def add_member_by_email(
    project_id: uuid.UUID,
    payload: ProjectMemberAdd,
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectMemberResponse:
    user_result = await db.execute(select(DBUser).where(DBUser.email == payload.email))
    target_user = user_result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    share_payload = ProjectShareRequest(user_id=target_user.id, permission=payload.permission)
    return await share_project(project_id, share_payload, current_user, db)
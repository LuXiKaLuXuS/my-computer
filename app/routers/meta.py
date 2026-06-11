import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dependencies.auth import get_current_active_user
from app.meta.agent import meta_agent
from app.meta.source_reader import ReadOnlySourceReader
from app.models.meta_proposal import DBMetaProposal, ProposalStatus
from app.models.user import DBUser

router = APIRouter(prefix="/meta", tags=["meta"])
settings = get_settings()


class AnalyzeRequest(BaseModel):
    focus: str = Field(default="orchestrator", max_length=200)


class ProposalCreate(BaseModel):
    title: str = Field(max_length=500)
    description: str
    file_changes: dict[str, str] = Field(default_factory=dict)


class ProposalResponse(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    status: str
    sandbox_result: dict | None
    file_changes: dict
    created_at: str


def _to_response(proposal: DBMetaProposal) -> ProposalResponse:
    return ProposalResponse(
        id=proposal.id,
        title=proposal.title,
        description=proposal.description,
        status=proposal.status.value if hasattr(proposal.status, "value") else str(proposal.status),
        sandbox_result=proposal.sandbox_result,
        file_changes=proposal.file_changes or {},
        created_at=proposal.created_at.isoformat(),
    )


@router.get("/status")
async def meta_status(
    current_user: DBUser = Depends(get_current_active_user),
) -> dict:
    return {
        "enabled": settings.meta_agent_enabled,
        "require_approval": settings.meta_agent_require_approval,
        "source_root": settings.meta_agent_source_root,
    }


@router.get("/source/files")
async def list_source_files(
    subdir: str = "app",
    current_user: DBUser = Depends(get_current_active_user),
) -> dict:
    reader = ReadOnlySourceReader()
    return {"files": reader.list_files(subdir)}


@router.get("/source/read")
async def read_source_file(
    path: str,
    current_user: DBUser = Depends(get_current_active_user),
) -> dict:
    reader = ReadOnlySourceReader()
    try:
        content = reader.read_file(path)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return {"path": path, "content": content}


@router.post("/analyze")
async def analyze_codebase(
    payload: AnalyzeRequest,
    current_user: DBUser = Depends(get_current_active_user),
) -> dict:
    if not settings.meta_agent_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Meta-agent disabled")
    return await meta_agent.analyze_codebase(payload.focus)


@router.post("/proposals", response_model=ProposalResponse, status_code=status.HTTP_201_CREATED)
async def create_proposal(
    payload: ProposalCreate,
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ProposalResponse:
    if not settings.meta_agent_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Meta-agent disabled")
    proposal = await meta_agent.create_proposal(
        db,
        user_id=current_user.id,
        title=payload.title,
        description=payload.description,
        file_changes=payload.file_changes,
    )
    return _to_response(proposal)


@router.get("/proposals", response_model=list[ProposalResponse])
async def list_proposals(
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProposalResponse]:
    result = await db.execute(
        select(DBMetaProposal)
        .where(DBMetaProposal.user_id == current_user.id)
        .order_by(DBMetaProposal.created_at.desc())
    )
    return [_to_response(p) for p in result.scalars().all()]


@router.get("/proposals/{proposal_id}", response_model=ProposalResponse)
async def get_proposal(
    proposal_id: uuid.UUID,
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ProposalResponse:
    result = await db.execute(
        select(DBMetaProposal).where(
            DBMetaProposal.id == proposal_id,
            DBMetaProposal.user_id == current_user.id,
        )
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    return _to_response(proposal)


@router.post("/proposals/{proposal_id}/approve", response_model=ProposalResponse)
async def approve_proposal(
    proposal_id: uuid.UUID,
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ProposalResponse:
    result = await db.execute(
        select(DBMetaProposal).where(
            DBMetaProposal.id == proposal_id,
            DBMetaProposal.user_id == current_user.id,
        )
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    try:
        proposal = await meta_agent.approve_proposal(
            db, proposal=proposal, approver_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _to_response(proposal)


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalResponse)
async def reject_proposal(
    proposal_id: uuid.UUID,
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ProposalResponse:
    result = await db.execute(
        select(DBMetaProposal).where(
            DBMetaProposal.id == proposal_id,
            DBMetaProposal.user_id == current_user.id,
        )
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    if proposal.status != ProposalStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only pending proposals can be rejected")
    proposal.status = ProposalStatus.REJECTED
    await db.flush()
    return _to_response(proposal)


@router.post("/proposals/{proposal_id}/apply")
async def apply_proposal(
    proposal_id: uuid.UUID,
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(DBMetaProposal).where(
            DBMetaProposal.id == proposal_id,
            DBMetaProposal.user_id == current_user.id,
        )
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    try:
        outcome = await meta_agent.apply_proposal(db, proposal)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return outcome
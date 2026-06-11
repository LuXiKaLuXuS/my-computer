import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory, get_db
from app.dependencies.auth import get_current_active_user
from app.models.goal import DBGoal
from app.schemas.goal import GoalCreate, GoalResponse, GoalRunRequest
from app.services.orchestrator import orchestrator
from app.services.webhook_delivery import notify_goal_completed
from app.models.user import DBUser

router = APIRouter(prefix="/goals", tags=["goals"])


async def _authenticate_ws(token: str | None, api_key: str | None) -> DBUser | None:

    from app.dependencies.auth import _get_user_by_api_key, _get_user_by_bearer
    from fastapi.security import HTTPAuthorizationCredentials

    async with async_session_factory() as db:
        if api_key:
            user = await _get_user_by_api_key(api_key, db)
            if user:
                await db.commit()
                return user
        if token:
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
            user = await _get_user_by_bearer(creds, db)
            if user:
                await db.commit()
                return user
    return None


@router.post("", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
async def create_goal(
    payload: GoalCreate,
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> DBGoal:
    goal = DBGoal(
        user_id=current_user.id,
        title=payload.title,
        description=payload.description,
        mode=payload.mode,
        project_id=payload.project_id,
        status="pending",
    )
    db.add(goal)
    await db.flush()
    await db.refresh(goal)
    return goal


@router.get("", response_model=list[GoalResponse])
async def list_goals(
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[DBGoal]:
    result = await db.execute(
        select(DBGoal)
        .where(DBGoal.user_id == current_user.id)
        .order_by(DBGoal.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{goal_id}", response_model=GoalResponse)
async def get_goal(
    goal_id: uuid.UUID,
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> DBGoal:
    result = await db.execute(
        select(DBGoal).where(DBGoal.id == goal_id, DBGoal.user_id == current_user.id)
    )
    goal = result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    return goal


@router.post("/run", response_model=GoalResponse)
async def run_goal(
    payload: GoalRunRequest,
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> DBGoal:
    goal = DBGoal(
        user_id=current_user.id,
        title=payload.goal[:500],
        description=payload.goal,
        mode=payload.mode,
        project_id=payload.project_id,
        status="running",
    )
    db.add(goal)
    await db.flush()

    result = await orchestrator.run(
        db,
        user_id=current_user.id,
        goal_id=goal.id,
        goal_text=payload.goal,
        mode=payload.mode,
    )

    goal.status = result["status"]
    goal.result = result
    goal.tokens_used = result.get("tokens_used", 0)
    goal.completed_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(goal)
    await notify_goal_completed(db, current_user.id, goal.id, result)
    return goal


@router.websocket("/ws/{goal_id}")
async def goal_progress_ws(websocket: WebSocket, goal_id: uuid.UUID) -> None:
    token = websocket.query_params.get("token")
    api_key = websocket.query_params.get("api_key")
    user = await _authenticate_ws(token, api_key)
    if not user:
        await websocket.close(code=4401)
        return

    await websocket.accept()

    async with async_session_factory() as db:
        result = await db.execute(
            select(DBGoal).where(DBGoal.id == goal_id, DBGoal.user_id == user.id)
        )
        goal = result.scalar_one_or_none()
        if not goal:
            await websocket.close(code=4404)
            return

        goal.status = "running"
        await db.commit()

        async def on_progress(step: str, message: str, data: dict) -> None:
            await websocket.send_json(
                {"type": "progress", "step": step, "message": message, "data": data}
            )

        try:
            run_result = await orchestrator.run(
                db,
                user_id=user.id,
                goal_id=goal.id,
                goal_text=goal.description or goal.title,
                mode=goal.mode,
                on_progress=on_progress,
            )
            goal.status = run_result["status"]
            goal.result = run_result
            goal.tokens_used = run_result.get("tokens_used", 0)
            goal.completed_at = datetime.now(timezone.utc)
            await notify_goal_completed(db, user.id, goal.id, run_result)
            await db.commit()
            await websocket.send_json({"type": "complete", "result": run_result})
        except WebSocketDisconnect:
            goal.status = "cancelled"
            await db.commit()
        except Exception as exc:
            goal.status = "failed"
            goal.result = {"error": str(exc)}
            await db.commit()
            await websocket.send_json({"type": "error", "message": str(exc)})
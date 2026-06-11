import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.auth import get_current_active_user
from app.models.user import DBUser
from app.services import webhook_delivery

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookRegister(BaseModel):
    url: HttpUrl
    events: list[str] = Field(default=["goal.completed", "goal.failed"])
    name: str = Field(default="Webhook", max_length=200)


class WebhookResponse(BaseModel):
    id: uuid.UUID
    url: str
    events: list[str]
    name: str
    is_active: bool
    secret: str | None = None


class DeadLetterResponse(BaseModel):
    id: uuid.UUID
    webhook_id: uuid.UUID
    event: str
    attempts: int
    last_error: str | None
    created_at: str


@router.post("", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
async def register_webhook(
    payload: WebhookRegister,
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> WebhookResponse:
    secret = secrets.token_urlsafe(32)
    webhook = await webhook_delivery.create_webhook(
        db,
        user_id=current_user.id,
        url=str(payload.url),
        events=payload.events,
        name=payload.name,
        secret=secret,
    )
    return WebhookResponse(
        id=webhook.id,
        url=webhook.url,
        events=webhook.events or [],
        name=webhook.name,
        is_active=webhook.is_active,
        secret=secret,
    )


@router.get("", response_model=list[WebhookResponse])
async def list_webhooks(
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[WebhookResponse]:
    webhooks = await webhook_delivery.list_webhooks(db, current_user.id)
    return [
        WebhookResponse(
            id=w.id,
            url=w.url,
            events=w.events or [],
            name=w.name,
            is_active=w.is_active,
        )
        for w in webhooks
        if w.is_active
    ]


@router.get("/dead-letters", response_model=list[DeadLetterResponse])
async def list_dead_letters(
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[DeadLetterResponse]:
    entries = await webhook_delivery.list_dead_letters(db, current_user.id)
    return [
        DeadLetterResponse(
            id=e.id,
            webhook_id=e.webhook_id,
            event=e.event,
            attempts=e.attempts,
            last_error=e.last_error,
            created_at=e.created_at.isoformat(),
        )
        for e in entries
    ]


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: uuid.UUID,
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if not await webhook_delivery.delete_webhook(db, current_user.id, webhook_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
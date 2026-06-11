from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_factory
from app.logging_config import get_logger
from app.models.webhook import DBWebhook, DBWebhookDeadLetter, DBWebhookDelivery

logger = get_logger(__name__)
settings = get_settings()


async def create_webhook(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    url: str,
    events: list[str],
    name: str = "Webhook",
    secret: str | None = None,
) -> DBWebhook:
    webhook = DBWebhook(
        user_id=user_id,
        name=name,
        url=url,
        events=events,
        secret=secret,
    )
    db.add(webhook)
    await db.flush()
    return webhook


async def list_webhooks(db: AsyncSession, user_id: uuid.UUID) -> list[DBWebhook]:
    result = await db.execute(
        select(DBWebhook)
        .where(DBWebhook.user_id == user_id)
        .order_by(DBWebhook.created_at.desc())
    )
    return list(result.scalars().all())


async def get_webhook(db: AsyncSession, user_id: uuid.UUID, webhook_id: uuid.UUID) -> DBWebhook | None:
    result = await db.execute(
        select(DBWebhook).where(DBWebhook.id == webhook_id, DBWebhook.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def delete_webhook(db: AsyncSession, user_id: uuid.UUID, webhook_id: uuid.UUID) -> bool:
    webhook = await get_webhook(db, user_id, webhook_id)
    if not webhook:
        return False
    webhook.is_active = False
    await db.flush()
    return True


def _sign_payload(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _deliver_once(webhook: DBWebhook, body: dict[str, Any]) -> tuple[bool, int | None, str | None]:
    payload_bytes = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    headers = {"Content-Type": "application/json"}
    if webhook.secret:
        headers["X-Webhook-Signature"] = _sign_payload(webhook.secret, payload_bytes)

    try:
        async with httpx.AsyncClient(timeout=settings.webhook_timeout_seconds) as client:
            resp = await client.post(webhook.url, content=payload_bytes, headers=headers)
            ok = 200 <= resp.status_code < 300
            return ok, resp.status_code, None if ok else resp.text[:500]
    except Exception as exc:
        return False, None, str(exc)


async def _process_delivery(delivery_id: uuid.UUID) -> None:
    async with async_session_factory() as db:
        result = await db.execute(
            select(DBWebhookDelivery, DBWebhook)
            .join(DBWebhook, DBWebhookDelivery.webhook_id == DBWebhook.id)
            .where(DBWebhookDelivery.id == delivery_id)
        )
        row = result.first()
        if not row:
            return
        delivery, webhook = row
        if not webhook.is_active:
            delivery.status = "cancelled"
            await db.commit()
            return

        body = {
            "event": delivery.event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": delivery.payload,
            "delivery_id": str(delivery.id),
        }

        success = False
        last_error: str | None = None
        last_code: int | None = None

        for attempt in range(1, settings.webhook_max_retries + 1):
            delivery.attempts = attempt
            success, last_code, last_error = await _deliver_once(webhook, body)
            delivery.last_status_code = last_code
            delivery.last_error = last_error
            if success:
                delivery.status = "delivered"
                delivery.delivered_at = datetime.now(timezone.utc)
                await db.commit()
                logger.info("webhook_delivered", webhook_id=str(webhook.id), event=delivery.event)
                return
            await asyncio.sleep(min(2 ** attempt, 8))

        delivery.status = "failed"
        dlq = DBWebhookDeadLetter(
            webhook_id=webhook.id,
            delivery_id=delivery.id,
            event=delivery.event,
            payload=delivery.payload,
            attempts=delivery.attempts,
            last_error=last_error,
        )
        db.add(dlq)
        await db.commit()
        logger.warning("webhook_dead_letter", webhook_id=str(webhook.id), event=delivery.event)


async def enqueue_event(
    db: AsyncSession,
    user_id: uuid.UUID,
    event: str,
    payload: dict[str, Any],
) -> list[uuid.UUID]:
    result = await db.execute(
        select(DBWebhook).where(
            DBWebhook.user_id == user_id,
            DBWebhook.is_active.is_(True),
        )
    )
    webhooks = list(result.scalars().all())
    delivery_ids: list[uuid.UUID] = []

    for webhook in webhooks:
        if event not in (webhook.events or []):
            continue
        delivery = DBWebhookDelivery(
            webhook_id=webhook.id,
            event=event,
            payload=payload,
            status="pending",
        )
        db.add(delivery)
        await db.flush()
        delivery_ids.append(delivery.id)

    for did in delivery_ids:
        asyncio.create_task(_process_delivery(did))

    return delivery_ids


async def notify_goal_completed(
    db: AsyncSession,
    user_id: uuid.UUID,
    goal_id: uuid.UUID,
    result: dict[str, Any],
) -> None:
    await enqueue_event(
        db,
        user_id,
        "goal.completed",
        {"goal_id": str(goal_id), "result": result},
    )


async def list_dead_letters(
    db: AsyncSession, user_id: uuid.UUID, limit: int = 50
) -> list[DBWebhookDeadLetter]:
    result = await db.execute(
        select(DBWebhookDeadLetter)
        .join(DBWebhook, DBWebhookDeadLetter.webhook_id == DBWebhook.id)
        .where(DBWebhook.user_id == user_id)
        .order_by(DBWebhookDeadLetter.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
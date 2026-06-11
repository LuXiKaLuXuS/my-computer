import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_usage import DBLLMUsage
from app.services.llm import LLMResponse


async def log_llm_usage(
    db: AsyncSession,
    *,
    response: LLMResponse,
    user_id: uuid.UUID | None = None,
    goal_id: uuid.UUID | None = None,
    node: str | None = None,
    prompt_preview: str | None = None,
) -> DBLLMUsage:
    entry = DBLLMUsage(
        user_id=user_id,
        goal_id=goal_id,
        provider=response.provider,
        model=response.model,
        node=node,
        tokens_used=response.tokens_used,
        prompt_preview=(prompt_preview or "")[:500] or None,
    )
    db.add(entry)
    await db.flush()
    return entry
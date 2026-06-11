from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings
from app.database import engine
from app.services.embeddings import get_embedding_service
from app.services.llm import get_llm_provider
from app.services.vector_memory import vector_memory

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health")
async def health_check() -> dict[str, Any]:
    checks: dict[str, Any] = {
        "status": "healthy",
        "version": settings.app_version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {},
    }

    # Database
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["checks"]["database"] = {"status": "ok"}
    except Exception as exc:
        checks["status"] = "degraded"
        checks["checks"]["database"] = {"status": "error", "detail": str(exc)}

    # Vector store (ChromaDB)
    try:
        chroma_ok = vector_memory.is_available()
        checks["checks"]["vector_store"] = {
            "status": "ok" if chroma_ok else "degraded",
            "backend": "chromadb",
            "remote": chroma_ok,
        }
        if not chroma_ok:
            checks["status"] = "degraded"
    except Exception as exc:
        checks["status"] = "degraded"
        checks["checks"]["vector_store"] = {"status": "error", "detail": str(exc)}

    # LLM models
    llm = get_llm_provider()
    has_real_key = bool(
        settings.openai_api_key or settings.anthropic_api_key or settings.grok_api_key
    )
    using_mock = llm.active_provider == "mock"
    model_status = "ok" if has_real_key and not using_mock else "degraded"
    embedding = get_embedding_service()
    checks["checks"]["models"] = {
        "status": model_status,
        "provider": settings.llm_provider,
        "active_provider": llm.active_provider,
        "fallback_chain": settings.llm_fallback_chain,
        "openai_configured": bool(settings.openai_api_key),
        "anthropic_configured": bool(settings.anthropic_api_key),
        "grok_configured": bool(settings.grok_api_key),
        "embedding_provider": settings.embedding_provider,
        "embedding_active": embedding.provider,
        "note": None if has_real_key and not using_mock else "Running in mock LLM mode",
    }
    if using_mock and checks["status"] == "healthy":
        checks["status"] = "degraded"

    checks["checks"]["meta_agent"] = {
        "enabled": settings.meta_agent_enabled,
        "require_approval": settings.meta_agent_require_approval,
    }

    return checks
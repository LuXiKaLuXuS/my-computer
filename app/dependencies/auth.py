import uuid
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.api_key import DBApiKey
from app.models.user import DBUser
from app.services.security import decode_access_token, verify_api_key

bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def _get_user_by_api_key(api_key: str, db: AsyncSession) -> DBUser | None:
    prefix = api_key[:12] if len(api_key) >= 12 else api_key
    result = await db.execute(
        select(DBApiKey, DBUser)
        .join(DBUser, DBApiKey.user_id == DBUser.id)
        .where(
            DBApiKey.key_prefix == prefix,
            DBApiKey.is_active.is_(True),
            DBUser.is_active.is_(True),
        )
    )
    now = datetime.now(timezone.utc)
    for api_key_row, user in result.all():
        if not verify_api_key(api_key, api_key_row.key_hash):
            continue
        if api_key_row.expires_at and api_key_row.expires_at < now:
            continue
        api_key_row.last_used_at = now
        await db.flush()
        return user
    return None


async def _get_user_by_bearer(
    credentials: HTTPAuthorizationCredentials | None, db: AsyncSession
) -> DBUser | None:
    if not credentials or credentials.scheme.lower() != "bearer":
        return None
    user_id = decode_access_token(credentials.credentials)
    if not user_id:
        return None
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return None
    result = await db.execute(select(DBUser).where(DBUser.id == uid, DBUser.is_active.is_(True)))
    return result.scalar_one_or_none()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    api_key: str | None = Depends(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> DBUser:
    """Authenticate via Bearer token or X-API-Key header."""
    if api_key:
        user = await _get_user_by_api_key(api_key, db)
        if user:
            return user
    user = await _get_user_by_bearer(credentials, db)
    if user:
        return user
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_active_user(
    current_user: DBUser = Depends(get_current_user),
) -> DBUser:
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )
    return current_user
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.auth import get_current_active_user
from app.models.refresh_token import DBRefreshToken
from app.models.user import DBUser
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.security import (
    create_access_token,
    create_refresh_token_value,
    hash_password,
    hash_token,
    refresh_token_expires_at,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    existing = await db.execute(
        select(DBUser).where((DBUser.email == payload.email) | (DBUser.username == payload.username))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email or username already registered")

    user = DBUser(
        email=payload.email,
        username=payload.username,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    await db.flush()

    refresh_value = create_refresh_token_value()
    db.add(
        DBRefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh_value),
            expires_at=refresh_token_expires_at(),
        )
    )
    await db.flush()

    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=refresh_value,
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    result = await db.execute(select(DBUser).where(DBUser.email == payload.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive account")

    refresh_value = create_refresh_token_value()
    db.add(
        DBRefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh_value),
            expires_at=refresh_token_expires_at(),
        )
    )
    await db.flush()

    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=refresh_value,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    token_hash = hash_token(payload.refresh_token)
    result = await db.execute(
        select(DBRefreshToken, DBUser)
        .join(DBUser, DBRefreshToken.user_id == DBUser.id)
        .where(
            DBRefreshToken.token_hash == token_hash,
            DBRefreshToken.is_revoked.is_(False),
        )
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    refresh_row, user = row
    now = datetime.now(timezone.utc)
    if refresh_row.expires_at < now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    refresh_row.is_revoked = True
    new_refresh = create_refresh_token_value()
    db.add(
        DBRefreshToken(
            user_id=user.id,
            token_hash=hash_token(new_refresh),
            expires_at=refresh_token_expires_at(),
        )
    )
    await db.flush()

    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=new_refresh,
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: DBUser = Depends(get_current_active_user)) -> DBUser:
    return current_user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: RefreshRequest,
    current_user: DBUser = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    token_hash = hash_token(payload.refresh_token)
    result = await db.execute(
        select(DBRefreshToken).where(
            DBRefreshToken.token_hash == token_hash,
            DBRefreshToken.user_id == current_user.id,
            DBRefreshToken.is_revoked.is_(False),
        )
    )
    token_row = result.scalar_one_or_none()
    if token_row:
        token_row.is_revoked = True
        await db.flush()
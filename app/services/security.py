import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings

settings = get_settings()

API_KEY_PREFIX = "mc_"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token_value() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        if payload.get("type") != "access":
            return None
        subject = payload.get("sub")
        return str(subject) if subject else None
    except JWTError:
        return None


def generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, prefix, hash)."""
    raw = secrets.token_urlsafe(32)
    full_key = f"{API_KEY_PREFIX}{raw}"
    prefix = full_key[:12]
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    return full_key, prefix, key_hash


def verify_api_key(provided: str, stored_hash: str) -> bool:
    return hashlib.sha256(provided.encode()).hexdigest() == stored_hash


def refresh_token_expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
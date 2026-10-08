"""Password hashing and JWT token helpers."""

import datetime
from typing import Optional

import jwt
from passlib.context import CryptContext

from . import config

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# A valid bcrypt hash of a throwaway string, used to equalize response time
# when the submitted username does not exist (account-enumeration resistance).
DUMMY_PASSWORD_HASH = pwd_context.hash("dummy-password-for-timing-only")


def hash_password(password: str) -> str:
    """Return a bcrypt hash of ``password`` (never the plaintext)."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Return True if ``plain_password`` matches ``password_hash``."""
    return pwd_context.verify(plain_password, password_hash)


def create_access_token(
    subject: str, expires_delta: Optional[datetime.timedelta] = None
) -> str:
    """Issue an HS256 JWT carrying ``sub`` and ``exp`` claims."""
    if not config.AUTH_SECRET_KEY:
        raise RuntimeError("AUTH_SECRET_KEY is not set; cannot sign tokens")

    expire = datetime.datetime.now(datetime.timezone.utc) + (
        expires_delta
        or datetime.timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, config.AUTH_SECRET_KEY, algorithm="HS256")

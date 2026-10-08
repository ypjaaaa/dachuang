"""Authentication routes."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import config
from ..db import SessionLocal
from ..repositories import UserRepository
from ..security import DUMMY_PASSWORD_HASH, create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


def get_repository():
    session = SessionLocal()
    try:
        yield UserRepository(session)
    finally:
        session.close()


@router.post("/login")
def login(body: LoginRequest, repo: UserRepository = Depends(get_repository)):
    user = repo.get_by_username(body.username)

    if user is None:
        # Burn comparable time so response timing does not reveal whether the
        # username exists.
        verify_password(body.password, DUMMY_PASSWORD_HASH)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token(user.username)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": config.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }

"""Tests for the user-auth login capability."""

import os

os.environ.setdefault("AUTH_SECRET_KEY", "test-secret-key-for-tests-please-make-it-long-enough")

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app.main import app
from app.models import Base, User
from app.repositories import UserRepository
from app.routers.auth import get_repository
from app.security import create_access_token, hash_password, verify_password


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)

    with TestingSession() as session:
        session.add(User(username="alice", password_hash=hash_password("correct-horse")))
        session.commit()

    def override_get_repository():
        session = TestingSession()
        try:
            yield UserRepository(session)
        finally:
            session.close()

    app.dependency_overrides[get_repository] = override_get_repository
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


# --- Login endpoint ---

def test_login_success_returns_access_token(client):
    resp = client.post(
        "/auth/login", json={"username": "alice", "password": "correct-horse"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0


def test_login_wrong_password_returns_401(client):
    resp = client.post("/auth/login", json={"username": "alice", "password": "wrong"})
    assert resp.status_code == 401


def test_login_unknown_user_returns_401(client):
    resp = client.post(
        "/auth/login", json={"username": "nobody", "password": "whatever"}
    )
    assert resp.status_code == 401


def test_login_unknown_user_error_matches_wrong_password(client):
    wrong_pw = client.post("/auth/login", json={"username": "alice", "password": "wrong"})
    unknown_user = client.post(
        "/auth/login", json={"username": "nobody", "password": "whatever"}
    )
    assert wrong_pw.status_code == unknown_user.status_code == 401
    assert wrong_pw.json() == unknown_user.json()


def test_login_missing_field_returns_422(client):
    resp = client.post("/auth/login", json={"username": "alice"})
    assert resp.status_code == 422


def test_login_wrong_type_returns_422(client):
    resp = client.post("/auth/login", json={"username": "alice", "password": 12345})
    assert resp.status_code == 422


# --- Password hashing ---

def test_hash_and_verify_password():
    h = hash_password("s3cret")
    assert h != "s3cret"
    assert "s3cret" not in h
    assert h.startswith(("$2b$", "$2a$", "$2y$"))
    assert verify_password("s3cret", h) is True
    assert verify_password("wrong", h) is False


# --- JWT ---

def test_create_access_token_claims():
    token = create_access_token("alice")
    payload = pyjwt.decode(token, config.AUTH_SECRET_KEY, algorithms=["HS256"])
    assert payload["sub"] == "alice"
    assert "exp" in payload


# --- Repository ---

def test_repository_get_by_username():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)
    with Session() as s:
        s.add(User(username="bob", password_hash="x"))
        s.commit()

    with Session() as s:
        repo = UserRepository(s)
        assert repo.get_by_username("bob") is not None
        assert repo.get_by_username("missing") is None

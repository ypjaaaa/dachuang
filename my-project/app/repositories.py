"""Data-access layer for users."""

from sqlalchemy.orm import Session

from .models import User


class UserRepository:
    """Provides user lookups against the persistent store."""

    def __init__(self, session: Session):
        self._session = session

    def get_by_username(self, username: str) -> User | None:
        """Return the user with ``username``, or ``None`` if not found."""
        return self._session.query(User).filter(User.username == username).first()

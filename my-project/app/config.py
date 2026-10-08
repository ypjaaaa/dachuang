"""Application configuration.

Secrets are read from the environment and never hardcoded. In production you
must set ``AUTH_SECRET_KEY`` to a strong random value.
"""

import os

# JWT signing secret. Required to issue access tokens; must be set in the
# environment (no hardcoded fallback).
AUTH_SECRET_KEY = os.environ.get("AUTH_SECRET_KEY")

# Access token lifetime in minutes. Defaults to 24 hours.
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

# SQLAlchemy database URL.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./app.db")

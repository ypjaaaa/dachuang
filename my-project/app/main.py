"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import engine
from .models import Base
from .routers import auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="User Login API", lifespan=lifespan)
app.include_router(auth.router)


@app.get("/")
def health_check():
    return {"status": "ok"}

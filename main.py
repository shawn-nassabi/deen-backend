from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from api import chat
from api import reference
from api import hikmah
from api import account
from api import onboarding
from api import primers
from models.JWTBearer import JWTBearer
from core.auth import jwks
from core.config import validate_supabase_config
import core.sentry  # side-effect: initializes Sentry SDK when SENTRY_ENABLED=true AND SENTRY_DSN set
from core.sentry import SENTRY_ENABLED
import os

from db.session import engine, Base          # for optional table bootstrap
from db.routers import (
    lessons as lessons_router,
    lesson_content as lesson_content_router,
    user_progress as user_progress_router,
    users as users_router,
    hikmah_trees as hikmah_trees_router,
)
from api import memory_admin


# RUN USING: uvicorn main:app --reload
@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_supabase_config()
    yield

app = FastAPI(lifespan=lifespan)

auth = JWTBearer(jwks)

# Comma-separated list from env, e.g.:
# CORS_ALLOW_ORIGINS="https://deen-frontend.vercel.app,https://staging.example.com"
raw = os.getenv("CORS_ALLOW_ORIGINS", "https://deen-frontend.vercel.app")
allow_origins = [o.strip() for o in raw.split(",") if o.strip()]

# In development, allow localhost origins
if os.getenv("ENV", "development") == "development":
    allow_origins.extend([
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ])

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from core.middleware import CorrelationIdMiddleware
app.add_middleware(CorrelationIdMiddleware)  # registered after CORS → runs first (insert(0) semantics)

# API routers
# app.include_router(reference.ref_router,dependencies=[Depends(auth)])
# app.include_router(chat.chat_router,dependencies=[Depends(auth)])
# app.include_router(hikmah.hikmah_router,dependencies=[Depends(auth)])
# app.include_router(account.router,dependencies=[Depends(auth)])  # /account

app.include_router(reference.ref_router)
app.include_router(chat.chat_router)
app.include_router(hikmah.hikmah_router)
app.include_router(account.router)                  # /account
app.include_router(onboarding.router)               # /onboarding

app.include_router(users_router.router)             # /users
app.include_router(lessons_router.router)           # /lessons
app.include_router(lesson_content_router.router)    # /lesson-content
app.include_router(user_progress_router.router)     # /user-progress
app.include_router(hikmah_trees_router.router)      # /hikmah-trees
app.include_router(memory_admin.router)             # /admin/memory
app.include_router(primers.primers_router)          # /primers


import logging
from fastapi.responses import JSONResponse
from fastapi.requests import Request

logger = logging.getLogger(__name__)

@app.middleware("http")
async def catch_exceptions_mw(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        logger.error(
            "Unhandled exception",
            exc_info=True,
            extra={"path": str(request.url.path)},
        )
        if SENTRY_ENABLED:
            return JSONResponse(status_code=500, content={"detail": "internal_error"})
        return JSONResponse(
            status_code=500,
            content={"detail": "internal_error", "error": str(e)},
        )

from sqlalchemy import text
from db.session import engine

@app.get("/_debug/db")
def db_ping():
    with engine.connect() as conn:
        v = conn.execute(text("SELECT version();")).scalar()
    return {"ok": True, "version": v}
# (DEV ONLY) uncomment once to create tables if the DB is empty
# Base.metadata.create_all(bind=engine)

@app.get("/")#,dependencies=[Depends(auth)])
def home():
    return {"message": "Welcome to the Shia Islam Chat API"}

@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}

# Optional: quick route lister for debugging (remove later)
from fastapi.routing import APIRoute
@app.get("/_routes")
def _routes():
    return [{"path": r.path, "methods": list(r.methods)} for r in app.routes if isinstance(r, APIRoute)]

if os.getenv("ENV", "development") == "development":
    @app.get("/sentry-debug", tags=["Debug"])
    def trigger_sentry_error():
        """Dev-only endpoint to verify Sentry error capture is working."""
        division_by_zero = 1 / 0

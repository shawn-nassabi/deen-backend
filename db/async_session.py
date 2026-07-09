from typing import AsyncIterator

from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import settings


def _build_async_database_url() -> str:
    override = getattr(settings, "ASYNC_DATABASE_URL", None)
    if override:
        return override
    return URL.create(
        drivername="postgresql+asyncpg",
        username=settings.DB_USER,
        password=settings.DB_PASSWORD,
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        database=settings.DB_NAME,
    ).render_as_string(hide_password=False)


async_engine = create_async_engine(
    _build_async_database_url(),
    future=True,
    pool_pre_ping=True,
    echo=False,
    # Bounded pool — see db/session.py for the full connection-budget math.
    # Sole consumer of the Supabase session-mode pooler (5432, 15-client cap).
    # Per worker 2+1=3; Dockerfile `-w 2` -> 6 < 15, headroom 9.
    # Sync engine moved to transaction mode (6543) — see db/session.py.
    # Dockerfile `-w 2` -> 12 < 15 (Supabase session-mode client cap).
    # Recompute if the worker count changes.
    pool_size=2,
    max_overflow=1,
    pool_recycle=300,
    pool_timeout=30,
    # asyncpg's `ssl="require"` mirrors psycopg2's `sslmode=require` used by the
    # sync engine in db/session.py — encrypt but skip cert chain verification.
    # Supabase's CA isn't in the local Python trust store on Windows, so `ssl=True`
    # (full verify) breaks local dev. Prod containers hit the same code path.
    connect_args={"ssl": "require"},
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_db_async() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session

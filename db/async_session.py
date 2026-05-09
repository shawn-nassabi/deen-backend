from typing import AsyncIterator

from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import settings


def _build_async_database_url() -> str:
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

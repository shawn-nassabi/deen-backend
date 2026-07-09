from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

# Set echo to False to avoid SQL statement noise in logs
## Sync engine targets the Supabase TRANSACTION-mode pooler (port 6543, via
# settings.DATABASE_URL / DB_SYNC_PORT): connections multiplex per-transaction,
# so pooled clients hold no session-mode slots. The 15-slot session-mode cap
# (port 5432) belongs entirely to the async engine (db/async_session.py).
# Pool stays bounded (2+1) as hygiene against runaway connection creation;
# pool_recycle=300 drops idle connections, pool_timeout=30 fails fast.
engine = create_engine(
    settings.DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    echo=False,
    pool_size=2,
    max_overflow=1,
    pool_recycle=300,
    pool_timeout=30,
    connect_args={"sslmode": "require"},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

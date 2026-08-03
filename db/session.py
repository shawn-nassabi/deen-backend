from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

# Set echo to False to avoid SQL statement noise in logs
# Connection budget for the Supabase pooler in SESSION mode (port 5432), which
# caps total client connections at 15 (every open pooled connection holds a slot,
# even when idle).
#
# Per gunicorn worker:
#   sync engine  (here):                pool_size 2 + max_overflow 1 = 3
#   async engine (db/async_session.py): pool_size 2 + max_overflow 1 = 3
#   -> 6 connections per worker
# Dockerfile runs `-w 2`  ->  6 x 2 = 12 < 15.  (Headroom = 3.)
#
# IMPORTANT: if the Dockerfile worker count changes, recompute this budget.
# pool_recycle=300 drops idle connections before the pooler reaps them;
# pool_timeout=30 fails fast instead of hanging when the pool is saturated.
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

"""Regression tests for PYTHON-FASTAPI-12/11/Y: pool bounds, port routing,
and URL override behavior must not silently regress."""
from db.session import engine
from db import async_session as async_mod
from db.config import Settings


def _make_settings(**overrides):
    return Settings(
        _env_file=None,
        DB_USER="u", DB_PASSWORD="p", DB_HOST="h",
        DB_PORT=5432, DB_NAME="db",
        **overrides,
    )


def test_sync_url_env_override_wins():
    s = _make_settings(DATABASE_URL_OVERRIDE="postgresql://u:p@h:6543/db")
    assert s.DATABASE_URL == "postgresql://u:p@h:6543/db"   # verbatim


def test_sync_url_component_fallback_uses_sync_port():
    s = _make_settings()
    assert ":6543/" in s.DATABASE_URL      # sync builds on DB_SYNC_PORT
    assert "+psycopg2" in s.DATABASE_URL   # explicit driver on fallback
    assert s.DB_PORT == 5432               # asyncpg fallback port untouched


def test_sync_pool_is_bounded():
    assert engine.pool.size() == 2
    assert engine.pool._max_overflow == 1
    assert engine.pool._pre_ping is True


def test_async_url_override_honored(monkeypatch):
    monkeypatch.setattr(
        async_mod.settings, "ASYNC_DATABASE_URL",
        "postgresql+asyncpg://u:p@somehost:5432/db", raising=False,
    )
    assert async_mod._build_async_database_url() == "postgresql+asyncpg://u:p@somehost:5432/db"


def test_async_url_falls_back_to_components(monkeypatch):
    monkeypatch.setattr(async_mod.settings, "ASYNC_DATABASE_URL", None, raising=False)
    assert async_mod._build_async_database_url().startswith("postgresql+asyncpg://")
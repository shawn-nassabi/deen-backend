"""
Root pytest configuration for the deen-backend test suite.

Sets test-only environment defaults so that `core.config` import-time guards
(ANTHROPIC_API_KEY / PINECONE_API_KEY / DEEN_*_INDEX_NAME) don't blow up the
session, and so that core/memory.py falls back to in-process EphemeralHistory
instead of attempting a real Redis connection.

These defaults are only applied if the env var is unset — running against a
real .env (e.g. `pytest tests/db -q`) is unaffected.
"""

import os
import sys

_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

_TEST_ENV_DEFAULTS = {
    "ANTHROPIC_API_KEY": "test-anthropic-key",
    "PINECONE_API_KEY": "test-pinecone-key",
    "DEEN_DENSE_INDEX_NAME": "test-deen-dense",
    "DEEN_SPARSE_INDEX_NAME": "test-deen-sparse",
    "QURAN_DENSE_INDEX_NAME": "test-quran-dense",
    "DEEN_FIQH_DENSE_INDEX_NAME": "test-deen-fiqh-dense",
    "DEEN_FIQH_SPARSE_INDEX_NAME": "test-deen-fiqh-sparse",
    # Unreachable URL → core/memory.py:_redis_ok returns False → EphemeralHistory.
    # Switch to fakeredis:// in Phase 4 once the async wrapper lands.
    "REDIS_URL": "redis://127.0.0.1:1/0",
    "REDIS_KEY_PREFIX": "test:chat",
    "ENV": "test",
    # db/config.py instantiates pydantic Settings() at import. The fields are
    # required, so provide test-only placeholders. No real DB is touched —
    # services/chat_persistence_service falls through to EphemeralHistory and
    # SQLAlchemy session creation is lazy.
    "DB_USER": "test-user",
    "DB_PASSWORD": "test-password",
    "DB_HOST": "127.0.0.1",
    "DB_PORT": "5432",
    "DB_NAME": "test-db",
}

for _key, _val in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_key, _val)


pytest_plugins = ["tests.conftest_async_stubs"]

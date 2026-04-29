import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

ENV = os.getenv("ENV", "development")
SENTRY_DSN = os.getenv("SENTRY_DSN")  # Optional — absence disables Sentry silently

# Retrieve API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
DEEN_DENSE_INDEX_NAME = os.getenv("DEEN_DENSE_INDEX_NAME")
DEEN_SPARSE_INDEX_NAME = os.getenv("DEEN_SPARSE_INDEX_NAME")
QURAN_DENSE_INDEX_NAME = os.getenv("QURAN_DENSE_INDEX_NAME")
# Fiqh-specific indexes (separate from hadith/Quran indexes)
# No ValueError guard — absence should not block server startup; guard inside ingestion script only
DEEN_FIQH_DENSE_INDEX_NAME = os.getenv("DEEN_FIQH_DENSE_INDEX_NAME")
DEEN_FIQH_SPARSE_INDEX_NAME = os.getenv("DEEN_FIQH_SPARSE_INDEX_NAME")
DENSE_RESULT_WEIGHT = os.getenv("DENSE_RESULT_WEIGHT",0.8)
SPARSE_RESULT_WEIGHT = os.getenv("SPARSE_RESULT_WEIGHT",0.2)
REFERENCE_FETCH_COUNT = int(os.getenv("REFERENCE_FETCH_COUNT", 10))

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
KEY_PREFIX = os.getenv("REDIS_KEY_PREFIX", "dev:chat")
TTL_SECONDS = int(os.getenv("REDIS_TTL_SECONDS", "12000"))  # default 30d
MAX_MESSAGES = int(os.getenv("REDIS_MAX_MESSAGES", "30"))
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
LARGE_LLM = os.getenv("LARGE_LLM", "claude-sonnet-4-6")
SMALL_LLM = os.getenv("SMALL_LLM", "claude-haiku-4-5-20251001")

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL")
ASYNC_DATABASE_URL = os.getenv("ASYNC_DATABASE_URL")

# Individual DB components (alternative to DATABASE_URL)
DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# Startup guard: fail fast if any required API key is absent
if not ANTHROPIC_API_KEY or not PINECONE_API_KEY:
    raise ValueError("Missing API keys! Ensure ANTHROPIC_API_KEY and PINECONE_API_KEY are set in the .env file.")

def validate_supabase_config() -> None:
    """Call from app startup to fail-fast if Supabase vars are absent.

    Intentionally deferred (not inline at module level) so that test imports
    of core.config succeed without SUPABASE_URL set. Fires at server startup
    via main.py lifespan, providing the same fail-fast guarantee as the inline
    ANTHROPIC_API_KEY/PINECONE_API_KEY guards without breaking the test suite.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise ValueError("Missing Supabase config! Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env.")

# Check if keys are loaded (optional)
if not DEEN_DENSE_INDEX_NAME or not DEEN_SPARSE_INDEX_NAME:
    raise ValueError("Missing Index names! Ensure they are set in the .env file.")

# Database validation
def build_database_url():
    """Build DATABASE_URL from individual components if not provided"""
    if DATABASE_URL:
        return DATABASE_URL
    
    if all([DB_HOST, DB_NAME, DB_USER, DB_PASSWORD]):
        return f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    
    return None

def build_async_database_url():
    """Build ASYNC_DATABASE_URL from individual components if not provided"""
    if ASYNC_DATABASE_URL:
        return ASYNC_DATABASE_URL
    
    if all([DB_HOST, DB_NAME, DB_USER, DB_PASSWORD]):
        return f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    
    return None

# Build URLs if not provided directly
FINAL_DATABASE_URL = build_database_url()
FINAL_ASYNC_DATABASE_URL = build_async_database_url()

# Embedding Configuration (for personalized primers)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-mpnet-base-v2")
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "768"))

# Similarity thresholds for note filtering and signal quality
# Notes with max similarity to lesson content >= NOTE_FILTER_THRESHOLD are included
NOTE_FILTER_THRESHOLD = float(os.getenv("NOTE_FILTER_THRESHOLD", "0.4"))
# Personalization requires average similarity of filtered notes >= SIGNAL_QUALITY_THRESHOLD
SIGNAL_QUALITY_THRESHOLD = float(os.getenv("SIGNAL_QUALITY_THRESHOLD", "0.5"))

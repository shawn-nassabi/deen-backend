# db/config.py
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AliasChoices
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DB_USER: str = Field(validation_alias=AliasChoices("DB_USER", "POSTGRES_USER", "PGUSER"))
    DB_PASSWORD: str = Field(validation_alias=AliasChoices("DB_PASSWORD", "POSTGRES_PASSWORD", "PGPASSWORD"))
    DB_HOST: str = Field(validation_alias=AliasChoices("DB_HOST", "POSTGRES_HOST", "PGHOST"))
    DB_PORT: int = Field(validation_alias=AliasChoices("DB_PORT", "POSTGRES_PORT", "PGPORT"))
    DB_NAME: str = Field(validation_alias=AliasChoices("DB_NAME", "POSTGRES_DB", "PGDATABASE", "DATABASE_NAME"))

    # Sync engine port — transaction-mode pooler (6543): psycopg2 is compatible,
    # connections multiplex, no session-slot cost. DB_PORT (5432) remains the
    # asyncpg fallback port and MUST stay on session mode.
    DB_SYNC_PORT: int = 6543

    # Explicit URL overrides. When set, they win over component-built URLs.
    # Accepts both the env var name (DATABASE_URL) and the field name, so
    # explicit construction in tests works: Settings(DATABASE_URL_OVERRIDE=...).
    DATABASE_URL_OVERRIDE: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("DATABASE_URL", "DATABASE_URL_OVERRIDE"),
    )
    ASYNC_DATABASE_URL: Optional[str] = None
    MIGRATION_DATABASE_URL: Optional[str] = None

    @property
    def DATABASE_URL(self) -> str:
        """Sync engine (psycopg2) connection URL.

        Explicit DATABASE_URL env var wins; otherwise built from DB_*
        components on DB_SYNC_PORT (transaction-mode pooler, 6543).
        """
        if self.DATABASE_URL_OVERRIDE:
            return self.DATABASE_URL_OVERRIDE
        return URL.create(
            drivername="postgresql+psycopg2",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_SYNC_PORT,
            database=self.DB_NAME,
        ).render_as_string(hide_password=False)


settings = Settings()
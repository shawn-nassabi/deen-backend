from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import os
import sys

# Ensure project root is on path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# Import metadata and settings from app
from db.session import Base
from db.config import settings

# this is the Alembic Config object
config = context.config

# Escape % to avoid ConfigParser interpolation issues
# Migrations prefer a session-mode connection (5432) via MIGRATION_DATABASE_URL
# over the transaction-mode pooler (6543) used by the app's sync engine.
# Falls back to DATABASE_URL when unset — behavior unchanged without the var.
_migration_url = settings.MIGRATION_DATABASE_URL or settings.DATABASE_URL
escaped_url = _migration_url.replace("%", "%%")
config.set_main_option("sqlalchemy.url", escaped_url)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

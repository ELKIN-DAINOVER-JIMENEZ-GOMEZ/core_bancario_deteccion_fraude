"""Entorno de Alembic: migraciones asíncronas (asyncpg) sobre los modelos de la app.

La URL se toma de la variable de entorno DATABASE_URL, la misma que usa el
servicio. No se usa `get_settings()` a propósito: migrar solo debe exigir la
base de datos, no Kafka ni la API key.
"""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.models import Base  # importar los modelos los registra en Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# Identificador (arbitrario pero fijo) del bloqueo que serializa las migraciones
MIGRATION_LOCK_ID = 7_352_418_901


def get_url() -> str:
    url = os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError(
            "Falta la base de datos: defina DATABASE_URL "
            "(postgresql+asyncpg://usuario:clave@host:5432/db)"
        )
    return url


def run_migrations_offline() -> None:
    """Genera el SQL sin conectarse (`alembic upgrade head --sql`)."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        # Varias réplicas pueden arrancar a la vez y ejecutar `alembic upgrade head`.
        # El bloqueo hace que las migraciones se apliquen de una en una; se libera
        # solo al terminar la transacción. Las demás réplicas esperan y, al
        # entrar, encuentran la base de datos ya migrada.
        connection.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": MIGRATION_LOCK_ID})
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        {"sqlalchemy.url": get_url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
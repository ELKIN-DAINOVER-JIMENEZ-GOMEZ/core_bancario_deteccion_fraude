"""Engine y sessionmaker asíncronos de SQLAlchemy (PostgreSQL + asyncpg).

Se crean de forma perezosa y una sola vez por proceso. La API y el consumer
de Kafka comparten el mismo pool de conexiones.
"""

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,  # descarta conexiones muertas antes de usarlas
        pool_size=10,
        max_overflow=10,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: los objetos siguen siendo legibles después del commit
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def dispose_engine() -> None:
    """Cierra el pool de conexiones. Se invoca al apagar el servicio."""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
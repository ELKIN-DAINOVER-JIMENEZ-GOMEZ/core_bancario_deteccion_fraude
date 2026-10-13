"""Punto de entrada del fraud-engine."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import api_router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.seed import seed_default_rules
from app.db.session import dispose_engine, get_sessionmaker
from app.kafka.consumer import FraudCheckConsumer
from app.kafka.producer import FraudEventProducer


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Inicia y detiene las conexiones externas del servicio."""
    settings = get_settings()
    setup_logging(settings.log_level)

    async with get_sessionmaker()() as session:
        await seed_default_rules(session)

    producer = FraudEventProducer(settings)
    consumer = FraudCheckConsumer(
        settings,
        sessionmaker=get_sessionmaker(),
        producer=producer,
    )
    await producer.start()
    try:
        await consumer.start()
        application.state.kafka_check = consumer.check
        yield
    finally:
        await consumer.stop()
        await producer.stop()
        await dispose_engine()


app = FastAPI(
    title="fraud-engine",
    description="Motor de detección de fraude de FinNode",
    lifespan=lifespan,
)
app.include_router(api_router)

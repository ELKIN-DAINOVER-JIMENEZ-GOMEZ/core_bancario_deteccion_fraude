"""Reglas por defecto del motor.

Se insertan solo si la tabla `fraud_rules` está vacía; a partir de ahí la
configuración vive en la base de datos y se ajusta con `PATCH /fraud/rules/{code}`.
Los montos están expresados en la moneda base del sistema (COP).

Para aplicarlas manualmente:  python -m app.db.seed
"""

import asyncio
import logging
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FraudRule
from app.repositories import RuleRepository

logger = logging.getLogger(__name__)

DEFAULT_RULES: tuple[dict[str, Any], ...] = (
    {
        "code": "SELF_TRANSFER",
        "description": "Cuenta origen igual a cuenta destino",
        "weight": 100,
        "blocking": True,
        "params": {},
    },
    {
        "code": "HIGH_AMOUNT",
        "description": "El monto supera el umbral absoluto",
        "weight": 30,
        "blocking": False,
        "params": {"threshold": 5_000_000},
    },
    {
        "code": "VELOCITY_COUNT",
        "description": "Demasiadas transacciones de la cuenta origen en una ventana corta",
        "weight": 35,
        "blocking": False,
        "params": {"max_count": 5, "window_minutes": 10},
    },
    {
        "code": "VELOCITY_AMOUNT",
        "description": "La suma de montos de la cuenta origen en la ventana supera un límite",
        "weight": 25,
        "blocking": False,
        "params": {"max_total": 10_000_000, "window_minutes": 60},
    },
    {
        "code": "NEW_BENEFICIARY_HIGH_AMOUNT",
        "description": "Primer envío a ese destino con un monto superior al umbral",
        "weight": 20,
        "blocking": False,
        "params": {"threshold": 1_000_000},
    },
    {
        "code": "AMOUNT_DEVIATION",
        "description": "El monto es varias veces mayor al promedio histórico de la cuenta",
        "weight": 25,
        "blocking": False,
        "params": {"multiplier": 5, "lookback_days": 30, "min_history": 3},
    },
    {
        "code": "UNUSUAL_HOUR",
        "description": "La transacción ocurre en horario de madrugada",
        "weight": 10,
        "blocking": False,
        "params": {"start_hour": 0, "end_hour": 5},
    },
)


async def seed_default_rules(session: AsyncSession) -> int:
    """Inserta las reglas por defecto si no hay ninguna. Devuelve cuántas insertó.

    Es seguro llamarla en cada arranque y desde varias réplicas a la vez: si
    otra réplica inserta primero, la restricción única sobre `code` hace que
    esta llamada no inserte nada.
    """
    repository = RuleRepository(session)
    if await repository.count() > 0:
        return 0

    try:
        await repository.add_many([FraudRule(**rule) for rule in DEFAULT_RULES])
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return 0

    logger.info("reglas por defecto insertadas", extra={"count": len(DEFAULT_RULES)})
    return len(DEFAULT_RULES)


async def _main() -> None:
    from app.core.logging import setup_logging
    from app.core.config import get_settings
    from app.db.session import dispose_engine, get_sessionmaker

    setup_logging(get_settings().log_level)
    try:
        async with get_sessionmaker()() as session:
            inserted = await seed_default_rules(session)
        print(f"Reglas insertadas: {inserted}")
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(_main())
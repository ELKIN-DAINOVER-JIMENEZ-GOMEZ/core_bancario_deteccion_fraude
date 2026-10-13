"""Acceso a datos de `fraud_evaluations`.

Además de guardar y consultar evaluaciones, expone las consultas de historial
que alimentan las reglas de comportamiento (velocidad, promedio, beneficiario).

Criterio de qué cuenta como historial:
- Velocidad (conteo y monto): todos los intentos, aprobados o rechazados.
- Promedio y beneficiario conocido: solo transacciones `APPROVED`.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Decision, FraudEvaluation


class EvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------ #
    # Escritura / consulta puntual
    # ------------------------------------------------------------------ #

    async def add(self, evaluation: FraudEvaluation) -> FraudEvaluation:
        """Agrega la evaluación a la sesión y la envía a la base de datos.

        Si ya existe una evaluación con el mismo `transaction_id`, el flush
        lanza `IntegrityError` (violación de la restricción UNIQUE). El
        servicio la interpreta como un duplicado concurrente.
        """
        self._session.add(evaluation)
        await self._session.flush()
        return evaluation

    async def get_by_transaction_id(self, transaction_id: str) -> FraudEvaluation | None:
        stmt = select(FraudEvaluation).where(
            FraudEvaluation.transaction_id == transaction_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    # ------------------------------------------------------------------ #
    # Listado paginado (API de auditoría)
    # ------------------------------------------------------------------ #

    async def list_paginated(
        self,
        *,
        account_id: uuid.UUID | None = None,
        decision: Decision | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[FraudEvaluation], int]:
        """Devuelve `(items, total)` ordenados de más reciente a más antiguo.

        `account_id` filtra por cuenta origen o destino.
        """
        filters = []
        if account_id is not None:
            filters.append(
                (FraudEvaluation.source_account_id == account_id)
                | (FraudEvaluation.destination_account_id == account_id)
            )
        if decision is not None:
            filters.append(FraudEvaluation.decision == decision)
        if date_from is not None:
            filters.append(FraudEvaluation.requested_at >= date_from)
        if date_to is not None:
            filters.append(FraudEvaluation.requested_at <= date_to)

        total = (
            await self._session.execute(
                select(func.count()).select_from(FraudEvaluation).where(*filters)
            )
        ).scalar_one()

        items_stmt = (
            select(FraudEvaluation)
            .where(*filters)
            .order_by(FraudEvaluation.requested_at.desc(), FraudEvaluation.id)
            .offset((page - 1) * size)
            .limit(size)
        )
        items = list((await self._session.execute(items_stmt)).scalars().all())
        return items, total

    # ------------------------------------------------------------------ #
    # Consultas de historial para las reglas
    # ------------------------------------------------------------------ #

    async def count_attempts_since(
        self, source_account_id: uuid.UUID, since: datetime
    ) -> int:
        """Intentos (aprobados o rechazados) de la cuenta origen desde `since`.

        Alimenta `VELOCITY_COUNT`.
        """
        stmt = select(func.count()).where(
            FraudEvaluation.source_account_id == source_account_id,
            FraudEvaluation.requested_at >= since,
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def sum_attempted_amount_since(
        self, source_account_id: uuid.UUID, since: datetime
    ) -> Decimal:
        """Suma de montos intentados (aprobados o rechazados) desde `since`.

        Alimenta `VELOCITY_AMOUNT`.
        """
        stmt = select(func.coalesce(func.sum(FraudEvaluation.amount), 0)).where(
            FraudEvaluation.source_account_id == source_account_id,
            FraudEvaluation.requested_at >= since,
        )
        return Decimal((await self._session.execute(stmt)).scalar_one())

    async def approved_amount_stats_since(
        self, source_account_id: uuid.UUID, since: datetime
    ) -> tuple[Decimal | None, int]:
        """Promedio y cantidad de transacciones `APPROVED` desde `since`.

        Devuelve `(promedio, cantidad)`; el promedio es `None` si no hay
        historial. Alimenta `AMOUNT_DEVIATION`.
        """
        stmt = select(
            func.avg(FraudEvaluation.amount), func.count()
        ).where(
            FraudEvaluation.source_account_id == source_account_id,
            FraudEvaluation.decision == Decision.APPROVED,
            FraudEvaluation.requested_at >= since,
        )
        avg, count = (await self._session.execute(stmt)).one()
        return (Decimal(avg) if avg is not None else None), count

    async def has_approved_transfer_to(
        self, source_account_id: uuid.UUID, destination_account_id: uuid.UUID
    ) -> bool:
        """Indica si la cuenta origen ya envió antes a ese destino (aprobado).

        Alimenta `NEW_BENEFICIARY_HIGH_AMOUNT`.
        """
        stmt = select(
            select(FraudEvaluation.id)
            .where(
                FraudEvaluation.source_account_id == source_account_id,
                FraudEvaluation.destination_account_id == destination_account_id,
                FraudEvaluation.decision == Decision.APPROVED,
            )
            .exists()
        )
        return bool((await self._session.execute(stmt)).scalar_one())
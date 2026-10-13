"""Arma el contexto de evaluación consultando el historial una sola vez."""

from collections.abc import Sequence
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.repositories import EvaluationRepository
from app.rules import (
    AmountStats,
    ApprovedAmountStats,
    AttemptCount,
    AttemptedAmount,
    KnownBeneficiary,
    Rule,
    RuleContext,
    SignalRequest,
)
from app.schemas.events import FraudCheckRequested


class FeatureBuilder:
    """Resuelve las señales que declaran las reglas activas.

    Las señales idénticas pedidas por varias reglas se consultan una sola vez.
    Las ventanas se miden hacia atrás desde el `timestamp` de la transacción
    (no desde "ahora"), lo que hace la evaluación reproducible.
    """

    def __init__(self, evaluations: EvaluationRepository, zone: ZoneInfo) -> None:
        self._evaluations = evaluations
        self._zone = zone

    async def build(
        self, transaction: FraudCheckRequested, rules: Sequence[Rule]
    ) -> RuleContext:
        requested: dict[SignalRequest, None] = {}  # dict: deduplica conservando el orden
        for rule in rules:
            for request in rule.required_signals():
                requested[request] = None

        # Secuencial: una AsyncSession no admite consultas concurrentes
        signals = {
            request: await self._resolve(request, transaction) for request in requested
        }
        return RuleContext(transaction=transaction, zone=self._zone, signals=signals)

    async def _resolve(self, request: SignalRequest, tx: FraudCheckRequested) -> Any:
        source = tx.source_account_id

        match request:
            case AttemptCount(window_minutes=minutes):
                since = tx.timestamp - timedelta(minutes=minutes)
                return await self._evaluations.count_attempts_since(source, since)
            case AttemptedAmount(window_minutes=minutes):
                since = tx.timestamp - timedelta(minutes=minutes)
                return await self._evaluations.sum_attempted_amount_since(source, since)
            case ApprovedAmountStats(lookback_days=days):
                since = tx.timestamp - timedelta(days=days)
                average, count = await self._evaluations.approved_amount_stats_since(
                    source, since
                )
                return AmountStats(average=average, count=count)
            case KnownBeneficiary():
                return await self._evaluations.has_approved_transfer_to(
                    source, tx.destination_account_id
                )
            case _:
                raise TypeError(f"Señal no soportada: {request!r}")
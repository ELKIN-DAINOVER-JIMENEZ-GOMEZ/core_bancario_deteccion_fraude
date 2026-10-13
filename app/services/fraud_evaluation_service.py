"""Orquesta la evaluación completa de una transacción.

    idempotencia → señales → reglas → score → persistir → publicar
"""

import logging
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import bind_transaction_id
from app.models import FraudEvaluation, FraudRule
from app.repositories import EvaluationRepository, RuleRepository
from app.rules import Rule, RuleContext, RuleResult
from app.schemas.evaluation import TriggeredRule
from app.schemas.events import FraudCheckCompleted, FraudCheckRequested
from app.services.feature_builder import FeatureBuilder
from app.services.risk_scorer import RiskScorer

logger = logging.getLogger(__name__)

# Construye las reglas ejecutables a partir de la configuración activa en BD
# (la provee el registry de reglas).
RuleFactory = Callable[[Sequence[FraudRule]], list[Rule]]


class CompletedEventPublisher(Protocol):
    """Lo que el servicio necesita del producer de Kafka."""

    async def publish_completed(self, event: FraudCheckCompleted) -> None: ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FraudEvaluationService:
    """Evalúa una solicitud y publica el resultado.

    Es dueño de la transacción de base de datos: confirma (commit) la
    evaluación antes de publicar. Usar una instancia (y una sesión) por mensaje.

    Garantías ante fallos (Kafka entrega al menos una vez):
    - Mensaje duplicado: no se reevalúa; se reenvía la decisión ya guardada.
    - Caída entre guardar y publicar: el reintento encuentra la evaluación y
      solo vuelve a publicar.
    - Dos duplicados simultáneos: el índice único sobre `transaction_id`
      deja pasar uno; el otro reenvía la decisión del primero.
    """

    def __init__(
        self,
        *,
        session: AsyncSession,
        evaluations: EvaluationRepository,
        rule_configs: RuleRepository,
        rule_factory: RuleFactory,
        feature_builder: FeatureBuilder,
        scorer: RiskScorer,
        publisher: CompletedEventPublisher,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._session = session
        self._evaluations = evaluations
        self._rule_configs = rule_configs
        self._rule_factory = rule_factory
        self._features = feature_builder
        self._scorer = scorer
        self._publisher = publisher
        self._clock = clock

    async def evaluate(self, request: FraudCheckRequested) -> FraudCheckCompleted:
        with bind_transaction_id(request.transaction_id):
            existing = await self._evaluations.get_by_transaction_id(request.transaction_id)
            if existing is not None:
                return await self._republish(existing)

            try:
                completed = await self._evaluate_and_store(request)
            except IntegrityError:
                # Carrera con un duplicado concurrente: ganó el otro
                await self._session.rollback()
                existing = await self._evaluations.get_by_transaction_id(
                    request.transaction_id
                )
                if existing is None:
                    raise  # fue otra violación de integridad, no un duplicado
                return await self._republish(existing)

            await self._publisher.publish_completed(completed)
            logger.info(
                "evaluación completada",
                extra={
                    "decision": completed.decision.value,
                    "riskScore": completed.risk_score,
                    "triggeredRules": [r.code for r in completed.triggered_rules],
                },
            )
            return completed

    # ------------------------------------------------------------------ #

    async def _evaluate_and_store(self, request: FraudCheckRequested) -> FraudCheckCompleted:
        configs = await self._rule_configs.list_enabled()
        snapshot_version = await self._rule_configs.get_snapshot_version()
        rules = self._rule_factory(configs)

        context = await self._features.build(request, rules)
        results = [self._run_rule(rule, context) for rule in rules]
        scored = self._scorer.score(results)

        evaluated_at = self._clock()
        triggered = [
            TriggeredRule(code=r.code, weight=r.weight, reason=r.reason) for r in scored.rules
        ]
        evaluation = FraudEvaluation(
            transaction_id=request.transaction_id,
            user_id=request.user_id,
            source_account_id=request.source_account_id,
            destination_account_id=request.destination_account_id,
            amount=request.amount,
            currency=request.currency,
            risk_score=scored.risk_score,
            decision=scored.decision,
            triggered_rules=[t.model_dump() for t in triggered],
            rules_snapshot_version=snapshot_version,
            requested_at=request.timestamp,
            evaluated_at=evaluated_at,  # explícito: evita recargar el valor de la BD
        )
        await self._evaluations.add(evaluation)
        await self._session.commit()

        return FraudCheckCompleted(
            transaction_id=request.transaction_id,
            decision=scored.decision,
            risk_score=scored.risk_score,
            triggered_rules=triggered,
            evaluated_at=evaluated_at,
        )

    @staticmethod
    def _run_rule(rule: Rule, context: RuleContext) -> RuleResult:
        """Una regla defectuosa no debe tumbar el motor: se registra y se omite."""
        try:
            return rule.evaluate(context)
        except Exception:  # noqa: BLE001
            logger.exception("regla fallida; se omite", extra={"rule": rule.code})
            return RuleResult(
                code=rule.code,
                triggered=False,
                reason="Regla omitida por error de ejecución",
                skipped=True,
            )

    async def _republish(self, evaluation: FraudEvaluation) -> FraudCheckCompleted:
        completed = FraudCheckCompleted(
            transaction_id=evaluation.transaction_id,
            decision=evaluation.decision,
            risk_score=evaluation.risk_score,
            triggered_rules=[TriggeredRule(**rule) for rule in evaluation.triggered_rules],
            evaluated_at=evaluation.evaluated_at,
        )
        await self._publisher.publish_completed(completed)
        logger.info("evaluación duplicada: se reenvía la decisión guardada")
        return completed
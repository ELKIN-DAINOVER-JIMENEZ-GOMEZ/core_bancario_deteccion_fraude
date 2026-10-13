"""Combina los resultados de las reglas en un score y una decisión."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.models import Decision
from app.rules import RuleResult

MAX_SCORE = 100


@dataclass(frozen=True)
class ScoreResult:
    risk_score: int
    decision: Decision
    # Reglas activadas y reglas omitidas por error, en el orden de ejecución
    rules: tuple[RuleResult, ...]


class RiskScorer:
    """Calcula `riskScore` y decide `APPROVED` / `REJECTED`.

        riskScore = min(100, suma de pesos de las reglas activadas)

        regla bloqueante activada      → REJECTED (riskScore = 100)
        riskScore >= reject_threshold  → REJECTED
        en otro caso                   → APPROVED

    Las reglas omitidas por error no suman puntos, pero se conservan en
    `rules` para que la auditoría las muestre.
    """

    def __init__(self, reject_threshold: int) -> None:
        if not 1 <= reject_threshold <= MAX_SCORE:
            raise ValueError(f"reject_threshold debe estar entre 1 y {MAX_SCORE}")
        self._reject_threshold = reject_threshold

    def score(self, results: Sequence[RuleResult]) -> ScoreResult:
        fired = [r for r in results if r.triggered and not r.skipped]
        reported = tuple(r for r in results if r.triggered or r.skipped)

        if any(r.blocking for r in fired):
            return ScoreResult(MAX_SCORE, Decision.REJECTED, reported)

        risk_score = min(MAX_SCORE, sum(r.weight for r in fired))
        decision = (
            Decision.REJECTED if risk_score >= self._reject_threshold else Decision.APPROVED
        )
        return ScoreResult(risk_score, decision, reported)
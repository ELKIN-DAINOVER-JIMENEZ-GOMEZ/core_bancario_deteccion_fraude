"""HIGH_AMOUNT — el monto supera un umbral absoluto."""

from collections.abc import Mapping
from typing import Any

from app.rules.base import Rule, RuleContext, RuleResult
from app.rules.helpers import format_amount, require_decimal


class HighAmountRule(Rule):
    """Se activa cuando `amount > threshold`.

    Parámetros: `threshold` (monto, > 0).
    """

    code = "HIGH_AMOUNT"

    def __init__(
        self, *, weight: int, blocking: bool = False, params: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(weight=weight, blocking=blocking, params=params)
        self._threshold = require_decimal(self.code, self.params, "threshold")

    def evaluate(self, context: RuleContext) -> RuleResult:
        tx = context.transaction
        if tx.amount > self._threshold:
            return self._hit(
                f"Monto de {format_amount(tx.amount)} {tx.currency} supera el umbral "
                f"de {format_amount(self._threshold)}"
            )
        return self._miss()
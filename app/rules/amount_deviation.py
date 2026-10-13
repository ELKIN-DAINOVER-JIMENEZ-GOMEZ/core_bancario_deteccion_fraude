"""AMOUNT_DEVIATION - monto muy superior al promedio aprobado."""

from collections.abc import Mapping, Sequence
from typing import Any

from app.rules.base import ApprovedAmountStats, Rule, RuleContext, RuleResult, SignalRequest
from app.rules.helpers import format_amount, require_decimal, require_int


class AmountDeviationRule(Rule):
    code = "AMOUNT_DEVIATION"

    def __init__(
        self, *, weight: int, blocking: bool = False, params: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(weight=weight, blocking=blocking, params=params)
        self._multiplier = require_decimal(self.code, self.params, "multiplier")
        self._lookback_days = require_int(self.code, self.params, "lookback_days", minimum=1)
        self._min_history = require_int(self.code, self.params, "min_history", minimum=1)

    def required_signals(self) -> Sequence[SignalRequest]:
        return (ApprovedAmountStats(self._lookback_days),)

    def evaluate(self, context: RuleContext) -> RuleResult:
        stats = context.signal(ApprovedAmountStats(self._lookback_days))
        if stats.count < self._min_history or stats.average is None:
            return self._miss()
        if context.transaction.amount > stats.average * self._multiplier:
            return self._hit(
                f"Monto {context.transaction.amount / stats.average:.1f}x superior "
                f"al promedio de {format_amount(stats.average)} {context.transaction.currency}"
            )
        return self._miss()

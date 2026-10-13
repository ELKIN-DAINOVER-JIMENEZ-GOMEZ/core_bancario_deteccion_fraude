"""VELOCITY_AMOUNT — demasiado dinero movido en poco tiempo."""

from collections.abc import Mapping, Sequence
from typing import Any

from app.rules.base import AttemptedAmount, Rule, RuleContext, RuleResult, SignalRequest
from app.rules.helpers import format_amount, require_decimal, require_int


class VelocityAmountRule(Rule):
    """Se activa cuando la suma de montos intentados por la cuenta origen en
    los últimos `window_minutes` supera `max_total`.

    La suma incluye la transacción que se está evaluando y cuenta intentos
    aprobados y rechazados.

    Parámetros: `max_total` (monto, > 0), `window_minutes` (>= 1).
    """

    code = "VELOCITY_AMOUNT"

    def __init__(
        self, *, weight: int, blocking: bool = False, params: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(weight=weight, blocking=blocking, params=params)
        self._max_total = require_decimal(self.code, self.params, "max_total")
        self._window = require_int(self.code, self.params, "window_minutes", minimum=1)

    def required_signals(self) -> Sequence[SignalRequest]:
        return (AttemptedAmount(self._window),)

    def evaluate(self, context: RuleContext) -> RuleResult:
        tx = context.transaction
        total = context.signal(AttemptedAmount(self._window)) + tx.amount
        if total > self._max_total:
            return self._hit(
                f"Suma de {format_amount(total)} {tx.currency} en {self._window} minutos "
                f"supera el límite de {format_amount(self._max_total)}"
            )
        return self._miss()
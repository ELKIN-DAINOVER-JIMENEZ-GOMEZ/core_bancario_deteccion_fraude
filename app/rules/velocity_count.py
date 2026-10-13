"""VELOCITY_COUNT — demasiadas transacciones seguidas desde la misma cuenta."""

from collections.abc import Mapping, Sequence
from typing import Any

from app.rules.base import AttemptCount, Rule, RuleContext, RuleResult, SignalRequest
from app.rules.helpers import require_int


class VelocityCountRule(Rule):
    """Se activa cuando la cuenta origen intentó más de `max_count`
    transacciones (aprobadas o rechazadas) en los últimos `window_minutes`.

    El conteo incluye la transacción que se está evaluando.

    Parámetros: `max_count` (>= 1), `window_minutes` (>= 1).
    """

    code = "VELOCITY_COUNT"

    def __init__(
        self, *, weight: int, blocking: bool = False, params: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(weight=weight, blocking=blocking, params=params)
        self._max_count = require_int(self.code, self.params, "max_count", minimum=1)
        self._window = require_int(self.code, self.params, "window_minutes", minimum=1)

    def required_signals(self) -> Sequence[SignalRequest]:
        return (AttemptCount(self._window),)

    def evaluate(self, context: RuleContext) -> RuleResult:
        attempts = context.signal(AttemptCount(self._window)) + 1  # + la actual
        if attempts > self._max_count:
            return self._hit(
                f"{attempts} transacciones en {self._window} minutos "
                f"(máx. {self._max_count})"
            )
        return self._miss()
"""UNUSUAL_HOUR — la transacción ocurre en horario de madrugada."""

from collections.abc import Mapping
from typing import Any

from app.rules.base import Rule, RuleContext, RuleResult
from app.rules.helpers import require_int


class UnusualHourRule(Rule):
    """Se activa cuando la hora local de la transacción cae en
    `[start_hour, end_hour)`: el inicio es inclusivo y el fin, exclusivo.

    Con los valores por defecto (0 y 5) cubre de 00:00 a 04:59. Si
    `start_hour > end_hour` el rango cruza la medianoche (por ejemplo,
    22 → 5 cubre de 22:00 a 04:59). Si son iguales, la regla nunca se activa.

    La hora se evalúa en la zona horaria configurada del servicio (`TIMEZONE`).

    Parámetros: `start_hour` (0–23), `end_hour` (0–24).
    """

    code = "UNUSUAL_HOUR"

    def __init__(
        self, *, weight: int, blocking: bool = False, params: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(weight=weight, blocking=blocking, params=params)
        self._start = require_int(self.code, self.params, "start_hour", minimum=0, maximum=23)
        self._end = require_int(self.code, self.params, "end_hour", minimum=0, maximum=24)

    def _in_window(self, hour: int) -> bool:
        if self._start < self._end:
            return self._start <= hour < self._end
        if self._start > self._end:  # cruza la medianoche
            return hour >= self._start or hour < self._end
        return False

    def evaluate(self, context: RuleContext) -> RuleResult:
        local = context.local_time
        if self._in_window(local.hour):
            return self._hit(f"Transacción a las {local:%H:%M} ({context.zone.key})")
        return self._miss()
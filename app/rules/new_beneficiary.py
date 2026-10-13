"""NEW_BENEFICIARY_HIGH_AMOUNT — primer envío a un destino, con monto alto."""

from collections.abc import Mapping, Sequence
from typing import Any

from app.rules.base import KnownBeneficiary, Rule, RuleContext, RuleResult, SignalRequest
from app.rules.helpers import format_amount, require_decimal


class NewBeneficiaryHighAmountRule(Rule):
    """Se activa cuando la cuenta origen nunca ha enviado (con éxito) a la
    cuenta destino **y** `amount > threshold`.

    Un monto bajo a un destino nuevo es normal; la combinación es la señal.

    Parámetros: `threshold` (monto, > 0).
    """

    code = "NEW_BENEFICIARY_HIGH_AMOUNT"

    def __init__(
        self, *, weight: int, blocking: bool = False, params: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(weight=weight, blocking=blocking, params=params)
        self._threshold = require_decimal(self.code, self.params, "threshold")

    def required_signals(self) -> Sequence[SignalRequest]:
        return (KnownBeneficiary(),)

    def evaluate(self, context: RuleContext) -> RuleResult:
        tx = context.transaction
        if tx.amount > self._threshold and not context.signal(KnownBeneficiary()):
            return self._hit(
                f"Primer envío a este destino con monto alto "
                f"({format_amount(tx.amount)} {tx.currency}, umbral {format_amount(self._threshold)})"
            )
        return self._miss()
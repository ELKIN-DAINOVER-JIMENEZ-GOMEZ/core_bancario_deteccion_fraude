"""SELF_TRANSFER — la cuenta origen y la destino son la misma."""

from app.rules.base import Rule, RuleContext, RuleResult


class SelfTransferRule(Rule):
    """Regla bloqueante: una transferencia de una cuenta a sí misma no tiene
    sentido de negocio y se rechaza sin importar el resto del score.

    No tiene parámetros. El carácter bloqueante y el peso vienen de la
    configuración (`blocking`, `weight`).
    """

    code = "SELF_TRANSFER"

    def evaluate(self, context: RuleContext) -> RuleResult:
        tx = context.transaction
        if tx.source_account_id == tx.destination_account_id:
            return self._hit("La cuenta origen y la cuenta destino son la misma")
        return self._miss()
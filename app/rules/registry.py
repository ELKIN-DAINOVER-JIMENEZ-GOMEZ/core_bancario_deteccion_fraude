"""Registro de reglas: mapa `code → clase` y construcción desde la configuración.

Para agregar una regla nueva: crear su clase, registrarla en `_BUILTIN_RULES`,
añadir su fila en `db/seed.py` y escribir sus pruebas.
"""

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from app.models import FraudRule
from app.rules.amount_deviation import AmountDeviationRule
from app.rules.base import Rule, RuleContext, RuleResult
from app.rules.helpers import InvalidRuleParamsError
from app.rules.high_amount import HighAmountRule
from app.rules.new_beneficiary import NewBeneficiaryHighAmountRule
from app.rules.self_transfer import SelfTransferRule
from app.rules.unusual_hour import UnusualHourRule
from app.rules.velocity_amount import VelocityAmountRule
from app.rules.velocity_count import VelocityCountRule

logger = logging.getLogger(__name__)

_BUILTIN_RULES: tuple[type[Rule], ...] = (
    SelfTransferRule,
    HighAmountRule,
    VelocityCountRule,
    VelocityAmountRule,
    NewBeneficiaryHighAmountRule,
    AmountDeviationRule,
    UnusualHourRule,
)


class RuleUnavailableError(RuntimeError):
    """La regla está configurada pero no se puede ejecutar."""


class _UnavailableRule(Rule):
    """Sustituto de una regla que no se pudo construir.

    Al fallar siempre al evaluarse, el servicio la registra como **omitida** y
    aparece en la auditoría de la evaluación. Así un error de configuración
    es visible en lugar de desaparecer en silencio, y no afecta a las demás.
    """

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(weight=0)
        self.code = code  # type: ignore[misc]  # instancia, no ClassVar
        self._reason = reason

    def evaluate(self, context: RuleContext) -> RuleResult:
        raise RuleUnavailableError(self._reason)


class RuleRegistry:
    def __init__(self, rules: Sequence[type[Rule]] = ()) -> None:
        self._classes: dict[str, type[Rule]] = {}
        for rule_class in rules:
            self.register(rule_class)

    def register(self, rule_class: type[Rule]) -> None:
        if rule_class.code in self._classes:
            raise ValueError(f"Ya existe una regla registrada con código '{rule_class.code}'")
        self._classes[rule_class.code] = rule_class

    @property
    def codes(self) -> frozenset[str]:
        return frozenset(self._classes)

    def build(self, configs: Sequence[FraudRule]) -> list[Rule]:
        """Construye las reglas ejecutables a partir de la configuración de la BD.

        Una regla sin implementación o con parámetros inválidos no interrumpe
        la evaluación: se sustituye por una regla "no disponible" (ver arriba).
        """
        rules: list[Rule] = []
        for config in configs:
            rule_class = self._classes.get(config.code)
            if rule_class is None:
                message = f"La regla '{config.code}' no tiene implementación registrada"
                logger.error(message)
                rules.append(_UnavailableRule(config.code, message))
                continue
            try:
                rules.append(
                    rule_class(weight=config.weight, blocking=config.blocking, params=config.params)
                )
            except InvalidRuleParamsError as exc:
                logger.error("configuración inválida de regla", extra={"rule": config.code, "error": str(exc)})
                rules.append(_UnavailableRule(config.code, str(exc)))
        return rules

    def validate_params(self, code: str, params: Mapping[str, Any]) -> None:
        """Comprueba que `params` sea una configuración válida para la regla.

        Lanza `ValueError` (`InvalidRuleParamsError`) si no lo es. Lo usa
        `RuleAdminService` para rechazar un `PATCH` que dejaría la regla rota.
        """
        rule_class = self._classes.get(code)
        if rule_class is None:
            raise ValueError(f"La regla '{code}' no tiene implementación registrada")
        rule_class(weight=0, params=params)  # el constructor valida


default_registry = RuleRegistry(_BUILTIN_RULES)

# Atajos para el resto de la aplicación
build_rules = default_registry.build
validate_rule_params = default_registry.validate_params
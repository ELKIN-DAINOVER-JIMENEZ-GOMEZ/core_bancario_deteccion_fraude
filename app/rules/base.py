"""Contrato del motor de reglas: `Rule`, `RuleContext` y `RuleResult`.

Las reglas son clases **puras**: no acceden a la base de datos ni a Kafka.
Reciben un `RuleContext` con la transacción y las señales de historial que
ellas mismas declararon necesitar (`required_signals`). El `FeatureBuilder`
resuelve esas señales una sola vez, aunque varias reglas pidan la misma.

Esto permite que cada regla use su propia ventana configurable (por ejemplo,
10 minutos para velocidad de conteo y 60 para velocidad de monto) sin
consultas duplicadas, y que se pruebe con un contexto armado a mano.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from app.schemas.events import FraudCheckRequested

# --------------------------------------------------------------------------- #
# Señales de historial que una regla puede solicitar
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AttemptCount:
    """Intentos previos de la cuenta origen (aprobados o rechazados) en la ventana.

    Valor resuelto: `int`. No incluye la transacción actual.
    """

    window_minutes: int


@dataclass(frozen=True)
class AttemptedAmount:
    """Suma de montos intentados por la cuenta origen en la ventana.

    Valor resuelto: `Decimal`. No incluye la transacción actual.
    """

    window_minutes: int


@dataclass(frozen=True)
class AmountStats:
    """Valor resuelto de `ApprovedAmountStats`."""

    average: Decimal | None  # None si no hay historial
    count: int


@dataclass(frozen=True)
class ApprovedAmountStats:
    """Promedio y cantidad de transacciones aprobadas de la cuenta origen.

    Valor resuelto: `AmountStats`.
    """

    lookback_days: int


@dataclass(frozen=True)
class KnownBeneficiary:
    """Si la cuenta origen ya envió antes (aprobado) a la cuenta destino.

    Valor resuelto: `bool`.
    """


SignalRequest = AttemptCount | AttemptedAmount | ApprovedAmountStats | KnownBeneficiary


# --------------------------------------------------------------------------- #
# Contexto y resultado
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RuleContext:
    """Todo lo que una regla necesita para decidir."""

    transaction: FraudCheckRequested
    zone: ZoneInfo
    signals: Mapping[SignalRequest, Any] = field(default_factory=dict)

    @property
    def local_time(self) -> datetime:
        """Momento de la transacción en la zona horaria configurada."""
        return self.transaction.timestamp.astimezone(self.zone)

    def signal(self, request: SignalRequest) -> Any:
        """Valor de una señal previamente declarada en `required_signals()`."""
        try:
            return self.signals[request]
        except KeyError:
            raise LookupError(
                f"Señal no disponible: {request}. "
                "La regla debe declararla en required_signals()."
            ) from None


@dataclass(frozen=True)
class RuleResult:
    """Resultado de ejecutar una regla."""

    code: str
    triggered: bool
    weight: int = 0
    blocking: bool = False
    reason: str = ""
    # True si la regla falló al ejecutarse y se omitió (no suma puntos)
    skipped: bool = False


# --------------------------------------------------------------------------- #
# Interfaz de las reglas
# --------------------------------------------------------------------------- #


class Rule(ABC):
    """Base de todas las reglas.

    Cada subclase define su `code` (el mismo de la tabla `fraud_rules`) y
    recibe en el constructor su configuración persistida.
    """

    code: ClassVar[str]

    def __init__(
        self,
        *,
        weight: int,
        blocking: bool = False,
        params: Mapping[str, Any] | None = None,
    ) -> None:
        self.weight = weight
        self.blocking = blocking
        self.params: dict[str, Any] = dict(params or {})

    def required_signals(self) -> Sequence[SignalRequest]:
        """Señales de historial que necesita; por defecto, ninguna."""
        return ()

    @abstractmethod
    def evaluate(self, context: RuleContext) -> RuleResult:
        """Evalúa la transacción. Debe ser determinista y no hacer I/O."""

    # Ayudas para construir el resultado desde las subclases
    def _hit(self, reason: str) -> RuleResult:
        return RuleResult(
            code=self.code,
            triggered=True,
            weight=self.weight,
            blocking=self.blocking,
            reason=reason,
        )

    def _miss(self) -> RuleResult:
        return RuleResult(code=self.code, triggered=False)
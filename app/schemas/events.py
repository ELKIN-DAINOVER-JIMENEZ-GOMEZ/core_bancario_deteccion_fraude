"""Contratos de los mensajes Kafka del fraud-engine.

- `FraudCheckRequested`: consumido de `fraud.check-requested` (lo publica el
  payment-orchestrator).
- `FraudCheckCompleted`: publicado en `fraud.check-completed` (lo consume el
  payment-orchestrator).

Ambos usan camelCase en el JSON y la key del mensaje es el `transactionId`.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Self

from pydantic import Field, field_validator

from app.models import Decision
from app.schemas.common import CamelModel
from app.schemas.evaluation import TriggeredRule

# Monto positivo con la misma precisión que la columna NUMERIC(19,4)
Amount = Annotated[Decimal, Field(gt=0, max_digits=19, decimal_places=4)]


class FraudCheckRequested(CamelModel):
    """Solicitud de evaluación de una transacción.

    Los campos desconocidos se ignoran, de modo que el orquestador puede
    agregar información al evento sin romper este servicio.
    """

    transaction_id: str = Field(min_length=1, max_length=64)
    user_id: uuid.UUID
    source_account_id: uuid.UUID
    destination_account_id: uuid.UUID
    amount: Amount
    currency: str = Field(pattern=r"^[A-Z]{3}$", description="ISO 4217, ej: COP")
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def _assume_utc(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    @classmethod
    def from_kafka_value(cls, raw: bytes | str) -> Self:
        """Deserializa el valor de un mensaje. Lanza `ValidationError` si es inválido."""
        return cls.model_validate_json(raw)


class FraudCheckCompleted(CamelModel):
    """Resultado de la evaluación."""

    transaction_id: str
    decision: Decision
    risk_score: int = Field(ge=0, le=100)
    triggered_rules: list[TriggeredRule]
    evaluated_at: datetime

    def to_kafka_value(self) -> bytes:
        """Serializa el evento a JSON (camelCase) listo para publicar."""
        return self.model_dump_json(by_alias=True).encode("utf-8")
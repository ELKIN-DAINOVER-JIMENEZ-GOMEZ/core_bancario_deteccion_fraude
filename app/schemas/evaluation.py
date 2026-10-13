"""Schemas HTTP de las evaluaciones de fraude (endpoints de auditoría)."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.models import Decision
from app.schemas.common import CamelModel


class TriggeredRule(CamelModel):
    """Una regla que se activó durante la evaluación."""

    code: str
    weight: int
    reason: str


class EvaluationResponse(CamelModel):
    id: uuid.UUID
    transaction_id: str
    user_id: uuid.UUID
    source_account_id: uuid.UUID
    destination_account_id: uuid.UUID
    amount: Decimal
    currency: str
    risk_score: int
    decision: Decision
    triggered_rules: list[TriggeredRule]
    rules_snapshot_version: str
    requested_at: datetime
    evaluated_at: datetime


class EvaluationFilter(CamelModel):
    """Parámetros de consulta de `GET /fraud/evaluations`.

    Las fechas sin zona horaria se interpretan como UTC.
    """

    model_config = ConfigDict(extra="forbid")

    account_id: uuid.UUID | None = Field(
        default=None, description="Cuenta origen o destino de la transacción"
    )
    decision: Decision | None = None
    date_from: datetime | None = Field(
        default=None, alias="from", description="Inicio del rango (requestedAt), inclusivo"
    )
    date_to: datetime | None = Field(
        default=None, alias="to", description="Fin del rango (requestedAt), inclusivo"
    )
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)

    @field_validator("date_from", "date_to")
    @classmethod
    def _assume_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @model_validator(mode="after")
    def _check_range(self) -> "EvaluationFilter":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("'from' no puede ser posterior a 'to'")
        return self

"""Entidad FraudEvaluation: registro auditable de cada evaluación de riesgo."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    DateTime,
    Enum,
    Index,
    Numeric,
    SmallInteger,
    String,
    CheckConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Decision(str, enum.Enum):
    """Decisión final del motor de fraude."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class FraudEvaluation(Base):
    """Resultado de evaluar una transacción.

    `transaction_id` es único y actúa como clave de idempotencia: si el mismo
    `fraud.check-requested` llega dos veces, no se reevalúa.
    """

    __tablename__ = "fraud_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    transaction_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    destination_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    risk_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    decision: Mapped[Decision] = mapped_column(
        Enum(Decision, name="fraud_decision", native_enum=False, length=20),
        nullable=False,
    )
    # Lista de {code, weight, reason} con las reglas que se activaron
    triggered_rules: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    rules_snapshot_version: Mapped[str] = mapped_column(String(20), nullable=False)

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="risk_score_range"),
        CheckConstraint("amount > 0", name="amount_positive"),
        # Consultas de velocidad y promedio por cuenta origen
        Index("ix_fraud_evaluations_source_requested", "source_account_id", "requested_at"),
        # Consulta de beneficiario conocido
        Index(
            "ix_fraud_evaluations_source_destination",
            "source_account_id",
            "destination_account_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"FraudEvaluation(transaction_id={self.transaction_id!r}, "
            f"risk_score={self.risk_score}, decision={self.decision.value})"
        )
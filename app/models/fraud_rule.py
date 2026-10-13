"""Entidad FraudRule: configuración de cada regla del motor."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FraudRule(Base):
    """Configuración persistida de una regla.

    Permite ajustar pesos, umbrales (`params`) y activación sin redesplegar.
    Si `blocking` es True, la regla rechaza la transacción sin importar el score.
    """

    __tablename__ = "fraud_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    weight: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint("weight >= 0 AND weight <= 100", name="weight_range"),
    )

    def __repr__(self) -> str:
        return f"FraudRule(code={self.code!r}, weight={self.weight}, enabled={self.enabled})"
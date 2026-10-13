
"""Esquema inicial del fraud-engine: evaluaciones y configuración de reglas.

- fraud_evaluations: registro auditable de cada evaluación. `transaction_id` es
  único (clave de idempotencia). Los índices sirven a las consultas de historial
  de las reglas (velocidad, promedio y beneficiario conocido).
- fraud_rules: configuración de cada regla (peso, parámetros, estado).

Las reglas por defecto NO se insertan aquí: las carga `app.db.seed` al arrancar
el servicio (solo si la tabla está vacía), de modo que su valor inicial no
queda congelado en el historial de migraciones.

Revision ID: 0001
Revises:
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fraud_evaluations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("transaction_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("source_account_id", sa.UUID(), nullable=False),
        sa.Column("destination_account_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("risk_score", sa.SmallInteger(), nullable=False),
        sa.Column(
            "decision",
            sa.Enum("APPROVED", "REJECTED", name="fraud_decision", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("triggered_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rules_snapshot_version", sa.String(length=20), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_fraud_evaluations_amount_positive")),
        sa.CheckConstraint(
            "risk_score >= 0 AND risk_score <= 100",
            name=op.f("ck_fraud_evaluations_risk_score_range"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fraud_evaluations")),
        sa.UniqueConstraint("transaction_id", name=op.f("uq_fraud_evaluations_transaction_id")),
    )
    op.create_index(
        "ix_fraud_evaluations_source_destination",
        "fraud_evaluations",
        ["source_account_id", "destination_account_id"],
        unique=False,
    )
    op.create_index(
        "ix_fraud_evaluations_source_requested",
        "fraud_evaluations",
        ["source_account_id", "requested_at"],
        unique=False,
    )

    op.create_table(
        "fraud_rules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("weight", sa.SmallInteger(), nullable=False),
        sa.Column("blocking", sa.Boolean(), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("weight >= 0 AND weight <= 100", name=op.f("ck_fraud_rules_weight_range")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fraud_rules")),
        sa.UniqueConstraint("code", name=op.f("uq_fraud_rules_code")),
    )


def downgrade() -> None:
    op.drop_table("fraud_rules")
    op.drop_index("ix_fraud_evaluations_source_requested", table_name="fraud_evaluations")
    op.drop_index("ix_fraud_evaluations_source_destination", table_name="fraud_evaluations")
    op.drop_table("fraud_evaluations")




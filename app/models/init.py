"""Modelos SQLAlchemy del fraud-engine.

Importar todos los modelos aquí garantiza que queden registrados en
`Base.metadata`, requisito para que Alembic detecte las tablas.
"""

from app.models.base import Base
from app.models.fraud_evaluation import Decision, FraudEvaluation
from app.models.fraud_rule import FraudRule

__all__ = ["Base", "Decision", "FraudEvaluation", "FraudRule"]
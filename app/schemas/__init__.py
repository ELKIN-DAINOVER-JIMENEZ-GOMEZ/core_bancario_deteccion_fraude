"""Contratos de datos (Pydantic) del fraud-engine."""

from app.schemas.common import CamelModel, ErrorResponse, Page
from app.schemas.events import FraudCheckCompleted, FraudCheckRequested
from app.schemas.evaluation import EvaluationFilter, EvaluationResponse, TriggeredRule
from app.schemas.rule import RuleResponse, RuleUpdateRequest

__all__ = [
    "CamelModel",
    "ErrorResponse",
    "EvaluationFilter",
    "EvaluationResponse",
    "FraudCheckCompleted",
    "FraudCheckRequested",
    "Page",
    "RuleResponse",
    "RuleUpdateRequest",
    "TriggeredRule",
]
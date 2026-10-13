"""Contratos HTTP para la administración de reglas."""

import uuid
from typing import Any

from pydantic import ConfigDict, Field

from app.schemas.common import CamelModel


class RuleResponse(CamelModel):
    id: uuid.UUID
    code: str
    description: str
    weight: int
    blocking: bool
    params: dict[str, Any]
    enabled: bool

    model_config = ConfigDict(from_attributes=True)


class RuleUpdateRequest(CamelModel):
    weight: int | None = Field(default=None, ge=0, le=100)
    blocking: bool | None = None
    params: dict[str, Any] | None = None
    enabled: bool | None = None

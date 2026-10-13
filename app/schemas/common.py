"""Piezas compartidas por los schemas HTTP."""

import math
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

T = TypeVar("T")


class CamelModel(BaseModel):
    """Base de los schemas: JSON en camelCase, atributos en snake_case.

    Coincide con la convención de los eventos Kafka (`transactionId`,
    `riskScore`, ...) y con el resto de microservicios de FinNode.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class Page(CamelModel, Generic[T]):
    """Respuesta paginada."""

    items: list[T]
    total: int
    page: int
    size: int
    pages: int

    @classmethod
    def build(cls, items: list[T], total: int, page: int, size: int) -> "Page[T]":
        return cls(
            items=items,
            total=total,
            page=page,
            size=size,
            pages=math.ceil(total / size) if total else 0,
        )


class ErrorResponse(CamelModel):
    detail: str
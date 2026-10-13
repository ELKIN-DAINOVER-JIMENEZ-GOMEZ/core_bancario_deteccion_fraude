"""Consulta de evaluaciones de fraude (auditoría). Solo lectura."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status

from app.api.deps import EvaluationRepoDep
from app.schemas import ErrorResponse, EvaluationFilter, EvaluationResponse, Page

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.get(
    "",
    response_model=Page[EvaluationResponse],
    summary="Listar evaluaciones",
)
async def list_evaluations(
    filters: Annotated[EvaluationFilter, Query()],
    repository: EvaluationRepoDep,
) -> Page[EvaluationResponse]:
    """Listado paginado, de la más reciente a la más antigua.

    `accountId` filtra por cuenta origen **o** destino. `from` y `to`
    delimitan el rango sobre la fecha de la transacción (`requestedAt`).
    """
    items, total = await repository.list_paginated(
        account_id=filters.account_id,
        decision=filters.decision,
        date_from=filters.date_from,
        date_to=filters.date_to,
        page=filters.page,
        size=filters.size,
    )
    return Page.build(
        [EvaluationResponse.model_validate(item) for item in items],
        total=total,
        page=filters.page,
        size=filters.size,
    )


@router.get(
    "/{transaction_id}",
    response_model=EvaluationResponse,
    summary="Detalle de una evaluación",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_evaluation(
    transaction_id: Annotated[str, Path(min_length=1, max_length=64)],
    repository: EvaluationRepoDep,
) -> EvaluationResponse:
    """Devuelve la evaluación de una transacción, con las reglas que se activaron."""
    evaluation = await repository.get_by_transaction_id(transaction_id)
    if evaluation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe evaluación para la transacción '{transaction_id}'",
        )
    return EvaluationResponse.model_validate(evaluation)
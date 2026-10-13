"""Consulta y ajuste de la configuración de las reglas."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status

from app.api.deps import RuleAdminDep
from app.schemas import ErrorResponse, RuleResponse, RuleUpdateRequest
from app.services import InvalidRuleConfigError, RuleNotFoundError

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get("", response_model=list[RuleResponse], summary="Listar reglas")
async def list_rules(service: RuleAdminDep) -> list[RuleResponse]:
    """Todas las reglas con su peso, parámetros y estado (activas o no)."""
    return [RuleResponse.model_validate(rule) for rule in await service.list_rules()]


@router.patch(
    "/{code}",
    response_model=RuleResponse,
    summary="Ajustar una regla",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        422: {"description": "Configuración inválida"},
    },
)
async def update_rule(
    code: Annotated[str, Path(min_length=1, max_length=50)],
    body: RuleUpdateRequest,
    service: RuleAdminDep,
) -> RuleResponse:
    """Modifica peso, bloqueo, parámetros o activación sin redesplegar.

    El cambio aplica a las evaluaciones siguientes. `params` se fusiona con los
    actuales y solo admite los parámetros que la regla ya define.
    """
    try:
        rule = await service.update_rule(
            code,
            weight=body.weight,
            blocking=body.blocking,
            params=body.params,
            enabled=body.enabled,
        )
    except RuleNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidRuleConfigError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return RuleResponse.model_validate(rule)
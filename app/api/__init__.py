"""Capa HTTP del fraud-engine.

`GET /health` es abierto. Todo lo que cuelga de `/fraud` es administrativo e
interno: exige la cabecera `X-Internal-Api-Key` y no se enruta desde el
api-gateway.
"""

from fastapi import APIRouter, Depends

from app.api import evaluations, health, rules
from app.api.deps import require_internal_api_key

fraud_router = APIRouter(
    prefix="/fraud",
    dependencies=[Depends(require_internal_api_key)],
    responses={401: {"description": "API key interna inválida o ausente"}},
)
fraud_router.include_router(evaluations.router)
fraud_router.include_router(rules.router)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(fraud_router)

__all__ = ["api_router"]
"""GET /health — estado del servicio (base de datos y Kafka)."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from app.api.deps import SessionDep
from app.schemas.common import CamelModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

CHECK_TIMEOUT_SECONDS = 2.0

Status = Literal["UP", "DOWN", "UNKNOWN"]


class HealthResponse(CamelModel):
    status: Literal["UP", "DOWN"]
    checks: dict[str, Status]


async def _run_check(name: str, check: Callable[[], Awaitable[object]]) -> Status:
    try:
        await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_SECONDS)
        return "UP"
    except Exception:  # noqa: BLE001 — cualquier fallo significa DOWN
        logger.warning("health check fallido", extra={"check": name}, exc_info=True)
        return "DOWN"


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Estado del servicio",
    responses={503: {"model": HealthResponse, "description": "Alguna dependencia no responde"}},
)
async def health(request: Request, response: Response, session: SessionDep) -> HealthResponse:
    """Verifica la base de datos y la conexión con Kafka.

    Responde `200` si todo está operativo y `503` en caso contrario.

    El chequeo de Kafka lo registra la aplicación al arrancar en
    `app.state.kafka_check` (una corrutina que falla si no hay conexión).
    Si no está registrado, el estado es `UNKNOWN` y el servicio se reporta `DOWN`.
    """
    checks: dict[str, Status] = {
        "database": await _run_check("database", lambda: session.execute(text("SELECT 1")))
    }

    kafka_check = getattr(request.app.state, "kafka_check", None)
    checks["kafka"] = "UNKNOWN" if kafka_check is None else await _run_check("kafka", kafka_check)

    healthy = all(value == "UP" for value in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="UP" if healthy else "DOWN", checks=checks)

"""Dependencias compartidas de la API: sesión de base de datos y seguridad."""

import secrets
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_sessionmaker
from app.repositories import EvaluationRepository
from app.services import RuleAdminService

# Aparece en Swagger UI como botón "Authorize".
_api_key_header = APIKeyHeader(name="X-Internal-Api-Key", auto_error=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Una sesión por petición.

    No confirma cambios automáticamente: quien escribe (por ejemplo,
    `RuleAdminService`) hace su propio commit. Al cerrar, cualquier
    transacción sin confirmar se revierte.
    """
    async with get_sessionmaker()() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def require_internal_api_key(
    settings: SettingsDep,
    api_key: Annotated[str | None, Depends(_api_key_header)],
) -> None:
    """Protege los endpoints administrativos `/fraud/**`."""
    expected = settings.internal_api_key.encode()
    provided = (api_key or "").encode()
    # compare_digest evita filtrar información por tiempos de respuesta
    if not api_key or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key interna inválida o ausente",
        )


def get_evaluation_repository(session: SessionDep) -> EvaluationRepository:
    return EvaluationRepository(session)


def get_rule_admin_service(session: SessionDep) -> RuleAdminService:
    return RuleAdminService(session)


EvaluationRepoDep = Annotated[EvaluationRepository, Depends(get_evaluation_repository)]
RuleAdminDep = Annotated[RuleAdminService, Depends(get_rule_admin_service)]
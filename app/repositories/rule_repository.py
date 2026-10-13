"""Acceso a datos de `fraud_rules` (configuración de las reglas)."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FraudRule

# Valor de versión cuando aún no existen reglas. Cabe en VARCHAR(20).
EMPTY_SNAPSHOT_VERSION = "0"


class RuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[FraudRule]:
        stmt = select(FraudRule).order_by(FraudRule.code)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_enabled(self) -> list[FraudRule]:
        """Reglas activas, las que ejecuta el motor en cada evaluación."""
        stmt = (
            select(FraudRule).where(FraudRule.enabled.is_(True)).order_by(FraudRule.code)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_by_code(self, code: str) -> FraudRule | None:
        stmt = select(FraudRule).where(FraudRule.code == code)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def count(self) -> int:
        return (
            await self._session.execute(select(func.count()).select_from(FraudRule))
        ).scalar_one()

    async def add_many(self, rules: Sequence[FraudRule]) -> None:
        """Inserta varias reglas (usado por el seed inicial)."""
        self._session.add_all(rules)
        await self._session.flush()

    async def update(
        self,
        rule: FraudRule,
        *,
        weight: int | None = None,
        blocking: bool | None = None,
        params: dict[str, Any] | None = None,
        enabled: bool | None = None,
    ) -> FraudRule:
        """Aplica cambios parciales; los campos `None` no se modifican.

        La validación de coherencia (pesos, parámetros) corresponde a
        `RuleAdminService`.
        """
        if weight is not None:
            rule.weight = weight
        if blocking is not None:
            rule.blocking = blocking
        if params is not None:
            rule.params = params
        if enabled is not None:
            rule.enabled = enabled
        await self._session.flush()
        await self._session.refresh(rule)  # recarga `updated_at` generado por la BD
        return rule

    async def get_snapshot_version(self) -> str:
        """Versión de la configuración vigente.

        Se deriva de la última modificación de cualquier regla
        (`YYYYMMDDHHMMSSffffff`, 20 caracteres), de modo que cada evaluación
        guardada indica con qué configuración se calculó.
        """
        latest = (
            await self._session.execute(select(func.max(FraudRule.updated_at)))
        ).scalar_one()
        if latest is None:
            return EMPTY_SNAPSHOT_VERSION
        return latest.strftime("%Y%m%d%H%M%S%f")
"""Administración de reglas: consulta y ajuste de configuración en caliente."""

from numbers import Real
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FraudRule
from app.repositories import RuleRepository


class RuleNotFoundError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(f"Regla '{code}' no encontrada")
        self.code = code


class InvalidRuleConfigError(ValueError):
    """La configuración propuesta para una regla no es coherente."""


def _is_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


class RuleAdminService:
    """Valida y aplica cambios de configuración.

    Este servicio es dueño de la transacción: confirma (commit) los cambios
    una vez aplicados.
    """

    def __init__(self, session: AsyncSession, repository: RuleRepository | None = None) -> None:
        self._session = session
        self._rules = repository or RuleRepository(session)

    async def list_rules(self) -> list[FraudRule]:
        return await self._rules.list_all()

    async def update_rule(
        self,
        code: str,
        *,
        weight: int | None = None,
        blocking: bool | None = None,
        params: dict[str, Any] | None = None,
        enabled: bool | None = None,
    ) -> FraudRule:
        rule = await self._rules.get_by_code(code)
        if rule is None:
            raise RuleNotFoundError(code)

        merged_params = None
        if params is not None:
            merged_params = self._merge_params(rule.params, params)

        updated = await self._rules.update(
            rule, weight=weight, blocking=blocking, params=merged_params, enabled=enabled
        )
        await self._session.commit()
        return updated

    @staticmethod
    def _merge_params(current: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
        """Fusiona `changes` sobre `current` validando claves y tipos.

        - Solo se aceptan parámetros que la regla ya define.
        - Los parámetros numéricos deben seguir siendo numéricos y no negativos.
        """
        unknown = sorted(set(changes) - set(current))
        if unknown:
            allowed = ", ".join(sorted(current)) or "(la regla no tiene parámetros)"
            raise InvalidRuleConfigError(
                f"Parámetros desconocidos: {', '.join(unknown)}. Permitidos: {allowed}"
            )

        for key, value in changes.items():
            if _is_number(current[key]):
                if not _is_number(value) or value < 0:
                    raise InvalidRuleConfigError(
                        f"El parámetro '{key}' debe ser un número mayor o igual a 0"
                    )
            elif type(value) is not type(current[key]):
                raise InvalidRuleConfigError(
                    f"El parámetro '{key}' debe ser de tipo {type(current[key]).__name__}"
                )

        return {**current, **changes}
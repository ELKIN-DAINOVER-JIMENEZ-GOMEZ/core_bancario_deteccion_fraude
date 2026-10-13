"""Utilidades compartidas por las reglas: validación de parámetros y formato.

Los parámetros de cada regla se guardan como JSON en `fraud_rules.params`, por
lo que pueden llegar como `int`, `float` o incluso con tipos incorrectos si
alguien los editó mal. Cada regla los valida y convierte al construirse.
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any


class InvalidRuleParamsError(ValueError):
    """Los parámetros configurados para una regla no son válidos."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"Regla {code}: {message}")
        self.code = code


def _raw_number(code: str, params: Mapping[str, Any], key: str) -> Decimal:
    if key not in params:
        raise InvalidRuleParamsError(code, f"falta el parámetro '{key}'")
    value = params[key]
    # bool es subclase de int: true/false no son números válidos aquí
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        raise InvalidRuleParamsError(code, f"el parámetro '{key}' debe ser numérico")
    number = Decimal(str(value))
    if not number.is_finite():
        raise InvalidRuleParamsError(code, f"el parámetro '{key}' debe ser un número finito")
    return number


def require_decimal(
    code: str, params: Mapping[str, Any], key: str, *, positive: bool = True
) -> Decimal:
    """Número decimal. Con `positive=True` exige > 0; si no, >= 0."""
    number = _raw_number(code, params, key)
    if (positive and number <= 0) or number < 0:
        bound = "mayor que 0" if positive else "mayor o igual a 0"
        raise InvalidRuleParamsError(code, f"el parámetro '{key}' debe ser {bound}")
    return number


def require_int(
    code: str,
    params: Mapping[str, Any],
    key: str,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    """Entero dentro de [minimum, maximum]. Acepta `10.0`, rechaza `10.5`."""
    number = _raw_number(code, params, key)
    if number != number.to_integral_value():
        raise InvalidRuleParamsError(code, f"el parámetro '{key}' debe ser un entero")
    integer = int(number)
    if integer < minimum or (maximum is not None and integer > maximum):
        limits = f">= {minimum}" if maximum is None else f"entre {minimum} y {maximum}"
        raise InvalidRuleParamsError(code, f"el parámetro '{key}' debe ser {limits}")
    return integer


def format_amount(value: Decimal) -> str:
    """Monto legible para los motivos: `6,000,000` o `1,250.50`."""
    if value == value.to_integral_value():
        return f"{value:,.0f}"
    return f"{value:,.2f}"
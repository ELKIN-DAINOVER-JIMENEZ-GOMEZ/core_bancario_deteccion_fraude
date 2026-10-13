"""Configuración del servicio, cargada desde variables de entorno.

Un único punto de acceso, tipado y validado al arrancar: si falta una variable
obligatoria o un valor es inválido, el servicio no inicia.
"""

from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Servicio ---------------------------------------------------------
    app_port: int = Field(default=8085, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # --- Base de datos ----------------------------------------------------
    # Ejemplo: postgresql+asyncpg://fraud_user:s3cr3t@fraud-db:5432/fraud_db
    database_url: str

    # --- Kafka ------------------------------------------------------------
    kafka_broker: str  # Ejemplo: kafka:9092
    kafka_group_id: str = "fraud-engine-group"
    topic_check_requested: str = "fraud.check-requested"
    topic_check_completed: str = "fraud.check-completed"
    topic_dlq: str = "fraud.check-requested.dlq"

    # --- Seguridad --------------------------------------------------------
    # Protege los endpoints administrativos /fraud/**
    internal_api_key: str = Field(min_length=1)

    # --- Motor de reglas --------------------------------------------------
    # Un riskScore mayor o igual a este valor produce REJECTED.
    reject_threshold: int = Field(default=70, ge=1, le=100)
    # Zona horaria usada por la regla UNUSUAL_HOUR.
    timezone: str = "America/Bogota"

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL debe usar el driver asíncrono: postgresql+asyncpg://..."
            )
        return value

    @field_validator("timezone")
    @classmethod
    def _require_valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Zona horaria desconocida: {value!r}") from exc
        return value

    @property
    def zoneinfo(self) -> ZoneInfo:
        """Zona horaria como objeto, lista para usar en las reglas."""
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    """Devuelve la configuración (se construye una sola vez por proceso)."""
    return Settings()  # type: ignore[call-arg]  # los campos obligatorios vienen del entorno
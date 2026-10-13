"""Producer de Kafka: publica los resultados y los mensajes fallidos (DLQ)."""

import logging
from datetime import datetime, timezone
from typing import Any

from aiokafka import AIOKafkaProducer

from app.core.config import Settings
from app.schemas.events import FraudCheckCompleted

logger = logging.getLogger(__name__)

_MAX_ERROR_HEADER_CHARS = 1000


class FraudEventProducer:
    """Envoltorio de `AIOKafkaProducer` con los dos mensajes que publica el servicio.

    - `fraud.check-completed`: la decisión de cada evaluación. Key = `transactionId`.
    - `fraud.check-requested.dlq`: mensajes que no se pudieron procesar, con
      cabeceras que explican el motivo.

    Todas las publicaciones esperan la confirmación del broker
    (`send_and_wait`): el consumer solo confirma el offset después de que
    la respuesta quedó realmente entregada.
    """

    def __init__(self, settings: Settings, *, producer: AIOKafkaProducer | None = None) -> None:
        self._settings = settings
        # Se puede inyectar un producer (pruebas); si no, se crea en start()
        self._producer = producer

    async def start(self) -> None:
        if self._producer is None:
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self._settings.kafka_broker,
                client_id="fraud-engine-producer",
                acks="all",  # el líder espera a todas las réplicas sincronizadas
                enable_idempotence=True,  # los reintentos internos no duplican mensajes
                linger_ms=5,
            )
        await self._producer.start()
        logger.info("producer de Kafka iniciado")

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            logger.info("producer de Kafka detenido")

    async def publish_completed(self, event: FraudCheckCompleted) -> None:
        """Publica la decisión en `fraud.check-completed`."""
        await self._require_started().send_and_wait(
            self._settings.topic_check_completed,
            key=event.transaction_id.encode("utf-8"),
            value=event.to_kafka_value(),
        )

    async def publish_dead_letter(
        self,
        *,
        key: bytes | None,
        value: bytes | None,
        error: BaseException | str,
        source_topic: str,
        source_partition: int,
        source_offset: int,
    ) -> None:
        """Reenvía un mensaje fallido a la DLQ, intacto, con el motivo en cabeceras."""
        message = error if isinstance(error, str) else f"{type(error).__name__}: {error}"
        headers: list[tuple[str, bytes]] = [
            ("x-error", message[:_MAX_ERROR_HEADER_CHARS].encode("utf-8")),
            ("x-source-topic", source_topic.encode("utf-8")),
            ("x-source-partition", str(source_partition).encode("utf-8")),
            ("x-source-offset", str(source_offset).encode("utf-8")),
            ("x-failed-at", datetime.now(timezone.utc).isoformat().encode("utf-8")),
        ]
        await self._require_started().send_and_wait(
            self._settings.topic_dlq, key=key, value=value, headers=headers
        )

    async def check(self) -> None:
        """Falla si no hay conexión con el broker. Alimenta `GET /health`."""
        producer = self._require_started()
        client: Any = producer.client
        await client.fetch_all_metadata()

    def _require_started(self) -> AIOKafkaProducer:
        if self._producer is None:
            raise RuntimeError("El producer no está iniciado: llamar a start() primero")
        return self._producer
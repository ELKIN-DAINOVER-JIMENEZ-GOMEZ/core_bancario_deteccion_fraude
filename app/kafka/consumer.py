"""Consumer de `fraud.check-requested`.

Corre como tarea de fondo dentro del ciclo de vida de FastAPI. Procesa los
mensajes **de uno en uno** y confirma el offset **solo después** de haber
guardado la evaluación y publicado la respuesta (semántica *al menos una vez*;
la idempotencia del servicio hace seguros los reintentos).

Qué pasa con cada mensaje:

    válido ──────────────► evaluar, publicar, confirmar offset
    inválido (JSON roto,
    campos erróneos) ────► DLQ, confirmar offset            (no bloquea la partición)
    fallo transitorio ───► reintentos con espera creciente
    reintentos agotados ─► DLQ, confirmar offset
    DLQ también falla ───► se sigue reintentando; sin confirmar offset

Un mensaje sin confirmar se vuelve a entregar tras un reinicio o rebalanceo.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any

from aiokafka import AIOKafkaConsumer, ConsumerRecord, TopicPartition
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.logging import bind_transaction_id
from app.kafka.producer import FraudEventProducer
from app.repositories import EvaluationRepository, RuleRepository
from app.rules import build_rules
from app.schemas.events import FraudCheckRequested
from app.services import FeatureBuilder, FraudEvaluationService, RiskScorer

logger = logging.getLogger(__name__)

POLL_TIMEOUT_MS = 1000
SHUTDOWN_TIMEOUT_SECONDS = 30.0

ServiceFactory = Callable[[AsyncSession], FraudEvaluationService]


class FraudCheckConsumer:
    def __init__(
        self,
        settings: Settings,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        producer: FraudEventProducer,
        consumer: AIOKafkaConsumer | None = None,
        service_factory: ServiceFactory | None = None,
        max_attempts: int = 5,
        retry_backoff_seconds: float = 1.0,
        retry_backoff_max_seconds: float = 30.0,
    ) -> None:
        self._settings = settings
        self._sessionmaker = sessionmaker
        self._producer = producer
        self._consumer = consumer  # se puede inyectar (pruebas); si no, se crea en start()
        self._service_factory = service_factory or self._default_service_factory
        self._max_attempts = max_attempts
        self._backoff = retry_backoff_seconds
        self._backoff_max = retry_backoff_max_seconds

        self._task: asyncio.Task[None] | None = None
        self._stop_requested = asyncio.Event()

    # ------------------------------------------------------------------ #
    # Ciclo de vida
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        if self._consumer is None:
            self._consumer = AIOKafkaConsumer(
                self._settings.topic_check_requested,
                bootstrap_servers=self._settings.kafka_broker,
                group_id=self._settings.kafka_group_id,
                client_id="fraud-engine-consumer",
                enable_auto_commit=False,  # el offset lo confirmamos nosotros
                auto_offset_reset="earliest",  # un grupo nuevo no se pierde mensajes previos
            )
        await self._consumer.start()
        self._stop_requested.clear()
        self._task = asyncio.create_task(self._run(), name="fraud-check-consumer")
        logger.info(
            "consumer de Kafka iniciado",
            extra={"topic": self._settings.topic_check_requested},
        )

    async def stop(self) -> None:
        """Termina el mensaje en curso, deja el grupo y cierra la conexión."""
        self._stop_requested.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=SHUTDOWN_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                logger.warning("el consumer no terminó a tiempo; se cancela")
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task
            self._task = None
        if self._consumer is not None:
            await self._consumer.stop()
        logger.info("consumer de Kafka detenido")

    async def check(self) -> None:
        """Falla si el bucle de consumo no está corriendo. Alimenta `GET /health`."""
        if self._task is None or self._task.done():
            raise RuntimeError("El consumer de Kafka no está en ejecución")

    # ------------------------------------------------------------------ #
    # Bucle principal
    # ------------------------------------------------------------------ #

    async def _run(self) -> None:
        assert self._consumer is not None
        while not self._stop_requested.is_set():
            try:
                # max_records=1: la posición solo avanza con el mensaje que
                # vamos a procesar, nunca sobre mensajes pendientes
                batch = await self._consumer.getmany(timeout_ms=POLL_TIMEOUT_MS, max_records=1)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — aiokafka reconecta; solo registrar y reintentar
                logger.exception("error leyendo de Kafka")
                if await self._wait(self._backoff):
                    return
                continue

            for records in batch.values():
                for record in records:
                    if not await self._handle(record):
                        return  # apagado en medio de un reintento: sin confirmar el offset

    async def _handle(self, record: ConsumerRecord) -> bool:
        """Procesa un mensaje hasta resolverlo. Devuelve False si se apagó antes."""
        last_error: BaseException | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                await self._process(record)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "fallo procesando mensaje",
                    extra={
                        "attempt": attempt,
                        "maxAttempts": self._max_attempts,
                        "offset": record.offset,
                        "partition": record.partition,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                    exc_info=attempt == self._max_attempts,
                )
                if attempt < self._max_attempts and await self._wait(self._delay(attempt)):
                    return False
            else:
                await self._commit(record)
                return True

        # Reintentos agotados: se aparta el mensaje para no bloquear la partición.
        # Si la DLQ tampoco responde, se insiste (sin avanzar el offset) hasta lograrlo.
        assert last_error is not None
        attempt = 0
        while True:
            try:
                await self._dead_letter(record, last_error)
                break
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                attempt += 1
                logger.exception("no se pudo publicar en la DLQ; se reintenta")
                if await self._wait(self._delay(attempt)):
                    return False
        await self._commit(record)
        return True

    async def _process(self, record: ConsumerRecord) -> None:
        """Evalúa un mensaje; uno inválido se envía a la DLQ en lugar de fallar."""
        try:
            if record.value is None:
                raise ValueError("mensaje sin contenido")
            request = FraudCheckRequested.from_kafka_value(record.value)
        except ValueError as exc:  # incluye pydantic.ValidationError
            logger.warning(
                "mensaje inválido: se envía a la DLQ",
                extra={"offset": record.offset, "partition": record.partition,
                       "error": self._describe(exc)},
            )
            await self._dead_letter(record, self._describe(exc))
            return

        with bind_transaction_id(request.transaction_id):
            async with self._sessionmaker() as session:
                await self._service_factory(session).evaluate(request)

    # ------------------------------------------------------------------ #
    # Auxiliares
    # ------------------------------------------------------------------ #

    async def _dead_letter(self, record: ConsumerRecord, error: BaseException | str) -> None:
        await self._producer.publish_dead_letter(
            key=record.key,
            value=record.value,
            error=error,
            source_topic=record.topic,
            source_partition=record.partition,
            source_offset=record.offset,
        )

    async def _commit(self, record: ConsumerRecord) -> None:
        """Confirma el offset del siguiente mensaje a leer.

        Si falla (por ejemplo, por un rebalanceo) no es grave: el mensaje se
        entregará de nuevo y la idempotencia evita reprocesarlo.
        """
        assert self._consumer is not None
        try:
            await self._consumer.commit({TopicPartition(record.topic, record.partition): record.offset + 1})
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.warning("no se pudo confirmar el offset; el mensaje podría repetirse", exc_info=True)

    def _delay(self, attempt: int) -> float:
        """Espera creciente: base, 2×base, 4×base... hasta el máximo."""
        return min(self._backoff * (2 ** (attempt - 1)), self._backoff_max)

    async def _wait(self, seconds: float) -> bool:
        """Espera `seconds`; devuelve True si durante la espera se pidió el apagado."""
        try:
            await asyncio.wait_for(self._stop_requested.wait(), timeout=seconds)
            return True
        except asyncio.TimeoutError:
            return False

    @staticmethod
    def _describe(exc: BaseException) -> str:
        """Motivo legible, sin incluir los valores recibidos (pueden ser datos sensibles)."""
        if isinstance(exc, ValidationError):
            return "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'json'}: {e['msg']}"
                for e in exc.errors(include_url=False, include_input=False, include_context=False)
            )
        return f"{type(exc).__name__}: {exc}"

    def _default_service_factory(self, session: AsyncSession) -> FraudEvaluationService:
        evaluations = EvaluationRepository(session)
        return FraudEvaluationService(
            session=session,
            evaluations=evaluations,
            rule_configs=RuleRepository(session),
            rule_factory=build_rules,
            feature_builder=FeatureBuilder(evaluations, self._settings.zoneinfo),
            scorer=RiskScorer(self._settings.reject_threshold),
            publisher=self._producer,
        )

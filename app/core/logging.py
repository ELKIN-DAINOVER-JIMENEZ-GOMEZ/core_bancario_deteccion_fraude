"""Logging estructurado en JSON con el `transactionId` en cada línea.

El identificador de la transacción se guarda en una `ContextVar`, de modo que
todo lo que se registre mientras se evalúa una transacción (reglas, repositorios,
producer) lo incluye automáticamente, sin pasarlo como argumento.

Uso:

    with bind_transaction_id(event.transaction_id):
        logger.info("evaluación iniciada")
"""

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

_transaction_id: ContextVar[str | None] = ContextVar("transaction_id", default=None)

# Atributos propios de LogRecord: lo que no esté aquí es un campo extra
# enviado con `logger.info("...", extra={...})` y se incluye en el JSON.
_RESERVED_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
) | {"message", "asctime", "taskName"}


@contextmanager
def bind_transaction_id(transaction_id: str) -> Iterator[None]:
    """Asocia el `transactionId` a todos los logs dentro del bloque."""
    token = _transaction_id.set(transaction_id)
    try:
        yield
    finally:
        _transaction_id.reset(token)


class JsonFormatter(logging.Formatter):
    """Serializa cada registro como una línea JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        transaction_id = _transaction_id.get()
        if transaction_id is not None:
            payload["transactionId"] = transaction_id

        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Configura el logger raíz para emitir JSON por stdout.

    Es idempotente: se puede llamar más de una vez sin duplicar handlers.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Uvicorn emite sus propias líneas: se redirigen al mismo formato JSON.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
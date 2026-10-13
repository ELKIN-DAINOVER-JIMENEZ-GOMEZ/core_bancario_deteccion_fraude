# 🛡️ fraud-engine — El Motor de Detección de Fraude

> Microservicio de FinNode responsable de evaluar el riesgo de cada transacción **antes** de que el dinero sea reservado. Está construido en **Python + FastAPI**, funciona con un **motor de reglas ponderadas** (sin modelo de Machine Learning entrenado) y se comunica con el resto del sistema **exclusivamente mediante Kafka**.

---

## 📋 Tabla de Contenidos

- [Responsabilidades](#-responsabilidades)
- [¿Por qué reglas y no Machine Learning?](#-por-qué-reglas-y-no-machine-learning)
- [Cómo se comunica con el sistema](#-cómo-se-comunica-con-el-sistema)
- [Endpoints](#-endpoints)
- [Estructura de Carpetas](#-estructura-de-carpetas)
- [Descripción de Cada Capa](#-descripción-de-cada-capa)
- [Motor de Reglas](#-motor-de-reglas)
- [Modelo de Base de Datos](#-modelo-de-base-de-datos)
- [Eventos Kafka](#-eventos-kafka)
- [Idempotencia y Tolerancia a Fallos](#-idempotencia-y-tolerancia-a-fallos)
- [Pruebas](#-pruebas)
- [Dependencias](#-dependencias)
- [Variables de Entorno](#-variables-de-entorno)
- [Dockerfile](#-dockerfile)
- [Flujo Interno](#-flujo-interno-evaluación-de-una-transacción)
- [Evolución hacia Machine Learning](#-evolución-hacia-machine-learning)

---

## ✅ Responsabilidades

| # | Responsabilidad | Descripción |
|---|----------------|-------------|
| 1 | **Evaluar riesgo** | Consume `fraud.check-requested`, ejecuta el conjunto de reglas activas y calcula un `riskScore` entre 0 y 100 |
| 2 | **Decidir** | Convierte el score en una decisión: `APPROVED` o `REJECTED` |
| 3 | **Responder** | Publica `fraud.check-completed` con la decisión, el score y las reglas que se activaron |
| 4 | **Auditar** | Persiste cada evaluación en PostgreSQL (quién, cuánto, qué reglas, qué decisión) para trazabilidad y análisis posterior |
| 5 | **Mantener historial** | Su propia tabla de evaluaciones alimenta las reglas de comportamiento (velocidad, monto promedio, beneficiario nuevo) |
| 6 | **Administrar reglas** | Permite consultar y ajustar pesos, umbrales y activación de reglas sin redesplegar código |

---

## 🧠 ¿Por qué reglas y no Machine Learning?

Este servicio **no utiliza un modelo entrenado**: es un sistema de scoring basado en reglas.

- No existe (todavía) un dataset etiquetado de fraude para entrenar un modelo.
- Un motor de reglas es **explicable**: cada rechazo indica exactamente qué reglas se activaron, algo indispensable en un entorno bancario y regulatorio.
- A diferencia de reglas estáticas "todo o nada", aquí las reglas se **ponderan**, usan **señales de comportamiento** (velocidad, desviación del promedio, beneficiario nuevo) y son **configurables en base de datos**.
- La arquitectura separa `reglas → score → decisión`, de modo que en el futuro un modelo de ML pueda añadirse como una regla más (ver [Evolución hacia Machine Learning](#-evolución-hacia-machine-learning)) sin tocar al resto de microservicios.

---

## 📡 Cómo se comunica con el sistema

`fraud-engine` **no expone ningún endpoint de negocio** y **nadie lo llama por HTTP** para evaluar un pago. Todo ocurre por Kafka:

```
payment-orchestrator                     fraud-engine
        │                                     │
        │── fraud.check-requested ───────────▶│  (1) consume, evalúa reglas, guarda evaluación
        │                                     │
        │◀─────────── fraud.check-completed ──│  (2) publica decisión + score + reglas activadas
```

- El `payment-orchestrator` es el **único productor** de `fraud.check-requested` y el **único consumidor** de `fraud.check-completed`.
- La clave (key) de cada mensaje es el `transactionId`, lo que garantiza orden por transacción y permite correlacionar petición y respuesta.
- El servicio tampoco se expone en el `api-gateway`. Su API HTTP es solo de **salud y administración**, accesible dentro de la red interna de Docker.

---

## 🌐 Endpoints

```
GET   /health                                → Estado del servicio (DB y Kafka)
GET   /fraud/evaluations/{transactionId}     → Detalle de una evaluación (auditoría)
GET   /fraud/evaluations                     → Listado paginado (filtros: accountId, decision, from, to)
GET   /fraud/rules                           → Lista de reglas con peso, parámetros y estado
PATCH /fraud/rules/{code}                    → Ajustar peso, parámetros o activar/desactivar una regla
GET   /docs                                  → Documentación OpenAPI (Swagger UI, generada por FastAPI)
```

> 🔒 Los endpoints `/fraud/**` son **administrativos e internos**: se protegen con la cabecera `X-Internal-Api-Key` y no se enrutan desde el `api-gateway`.

---

## 📁 Estructura de Carpetas

```
fraud-engine/
├── app/
│   ├── main.py                                  ← Punto de entrada FastAPI (lifespan: arranca/para consumer y producer)
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                            ← Settings con pydantic-settings (variables de entorno)
│   │   └── logging.py                           ← Logging estructurado (JSON) con transactionId en cada línea
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py                              ← Dependencias: sesión de DB, validación de API key interna
│   │   ├── health.py                            ← GET /health
│   │   ├── evaluations.py                       ← Consulta de evaluaciones
│   │   └── rules.py                             ← Consulta y ajuste de reglas
│   │
│   ├── schemas/                                 ← Modelos Pydantic (contratos HTTP y Kafka)
│   │   ├── __init__.py
│   │   ├── common.py                            ← Esquemas compartidos (paginación, enums, tipos comunes)
│   │   ├── events.py                            ← FraudCheckRequested, FraudCheckCompleted
│   │   ├── evaluation.py                        ← EvaluationResponse, EvaluationFilter, Page
│   │   └── rule.py                              ← RuleResponse, RuleUpdateRequest
│   │
│   ├── models/                                  ← Entidades SQLAlchemy 2.0
│   │   ├── init.py                              ← Importa los modelos para que Alembic los detecte
│   │   ├── base.py                              ← DeclarativeBase
│   │   ├── fraud_evaluation.py                  ← Tabla fraud_evaluations
│   │   └── fraud_rule.py                        ← Tabla fraud_rules
│   │
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── evaluation_repository.py             ← Guardar/consultar evaluaciones + consultas de historial
│   │   └── rule_repository.py                   ← Cargar reglas activas, actualizar configuración
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── fraud_evaluation_service.py          ← Orquesta: idempotencia → features → reglas → score → persistir → publicar
│   │   ├── feature_builder.py                   ← Calcula señales de historial (conteo, suma, promedio, beneficiario conocido)
│   │   ├── risk_scorer.py                       ← Suma pesos, aplica tope 100 y umbral de decisión
│   │   └── rule_admin_service.py                ← Lógica de administración de reglas
│   │
│   ├── rules/                                   ← Cada regla es una clase pura, sin acceso a DB ni Kafka
│   │   ├── __init__.py
│   │   ├── base.py                              ← Interfaz Rule, RuleContext, RuleResult
│   │   ├── helpers.py                           ← Funciones auxiliares compartidas por las reglas
│   │   ├── registry.py                          ← Mapa código → clase de regla; construye reglas desde la config de DB
│   │   ├── high_amount.py                       ← HIGH_AMOUNT
│   │   ├── velocity_count.py                    ← VELOCITY_COUNT
│   │   ├── velocity_amount.py                   ← VELOCITY_AMOUNT
│   │   ├── new_beneficiary.py                   ← NEW_BENEFICIARY_HIGH_AMOUNT
│   │   ├── amount_deviation.py                  ← AMOUNT_DEVIATION
│   │   ├── unusual_hour.py                      ← UNUSUAL_HOUR
│   │   └── self_transfer.py                     ← SELF_TRANSFER (regla bloqueante)
│   │
│   ├── kafka/
│   │   ├── __init__.py
│   │   ├── consumer.py                          ← Loop aiokafka: escucha fraud.check-requested, maneja errores y DLQ
│   │   └── producer.py                          ← Publica fraud.check-completed
│   │
│   └── db/
│       ├── __init__.py
│       ├── session.py                           ← Engine y sessionmaker async (SQLAlchemy + asyncpg)
│       └── seed.py                              ← Reglas por defecto (se insertan si la tabla está vacía)
│
├── alembic/
│   ├── env.py
│   ├── script.py
│   └── versions/                                ← Migraciones de esquema (ddl controlado, no auto-create)
│
├── tests/
│   ├── conftest.py                              ← Fixtures compartidas (contexto de ejemplo, fakes)
│   ├── unit/
│   │   ├── rules/                               ← Un archivo de test por regla
│   │   │   ├── test_high_amount.py
│   │   │   ├── test_velocity_count.py
│   │   │   ├── test_velocity_amount.py
│   │   │   ├── test_new_beneficiary.py
│   │   │   ├── test_amount_deviation.py
│   │   │   ├── test_unusual_hour.py
│   │   │   └── test_self_transfer.py
│   │   ├── test_risk_scorer.py                  ← Suma, tope 100, umbral, regla bloqueante
│   │   ├── test_feature_builder.py              ← Cálculo de señales con repositorio falso
│   │   ├── test_fraud_evaluation_service.py     ← Orquestación con repos y producer simulados (mocks)
│   │   └── test_rule_registry.py                ← Construcción de reglas desde configuración
│   └── integration/
│       ├── conftest.py                          ← Testcontainers: PostgreSQL + Kafka reales
│       ├── test_evaluation_repository.py        ← Consultas de historial contra PostgreSQL real
│       ├── test_kafka_flow.py                   ← Publicar check-requested → recibir check-completed
│       ├── test_idempotency.py                  ← Mismo transactionId dos veces = misma respuesta, 1 registro
│       └── test_api.py                          ← Endpoints con httpx.AsyncClient
│
├── alembic.ini
├── pyproject.toml                               ← Dependencias, configuración de pytest, ruff y coverage
├── uv.lock                                      ← Versiones exactas de dependencias
├── requirements.txt
├── README.md
├── fraud-engine-README.md                       ← Este documento
└── Dockerfile                                   ← Imagen Docker del servicio
```

---

## 📐 Descripción de Cada Capa

### `core/`
| Módulo | Qué hace |
|--------|----------|
| `config.py` | Clase `Settings` (pydantic-settings) que carga toda la configuración desde variables de entorno. Un solo lugar, tipado y validado al arrancar |
| `logging.py` | Logging en JSON; cada evaluación registra `transactionId`, `riskScore` y `decision` para poder rastrearla |

### `api/`
Capa HTTP mínima. No contiene lógica de negocio; solo valida entrada, llama a los servicios y devuelve respuestas.

### `schemas/`
Modelos Pydantic v2. Definen y validan los contratos tanto HTTP como de mensajes Kafka. Un mensaje malformado falla aquí y se envía a la DLQ.

### `models/` y `repositories/`
Entidades SQLAlchemy y acceso a datos. Los repositorios también exponen las consultas de historial que necesitan las reglas (por ejemplo: "cuántas transacciones hizo esta cuenta en los últimos 10 minutos").

### `services/`
| Clase | Qué hace |
|-------|----------|
| `FraudEvaluationService` | Flujo completo de una evaluación (ver [Flujo Interno](#-flujo-interno-evaluación-de-una-transacción)) |
| `FeatureBuilder` | Consulta el historial una sola vez y arma un objeto de señales (`RuleContext`) que reciben todas las reglas |
| `RiskScorer` | Combina resultados de reglas en un score y decide `APPROVED` / `REJECTED` |
| `RuleAdminService` | Actualiza reglas y valida que pesos y parámetros sean coherentes |

### `rules/`
Corazón del motor. Cada regla recibe un `RuleContext` (transacción + señales de historial) y devuelve un `RuleResult(triggered, weight, reason)`. **No hacen I/O**, por lo que se prueban con pruebas unitarias puras y rápidas.

### `kafka/`
Consumer y producer con `aiokafka`. El consumer corre como tarea de fondo dentro del ciclo de vida (`lifespan`) de FastAPI; el commit del offset se hace **después** de persistir y publicar el resultado (at-least-once + idempotencia).

---

## ⚖️ Motor de Reglas

### Reglas por defecto

Todos los valores son **configurables** en la tabla `fraud_rules` (columna `params`) y ajustables vía `PATCH /fraud/rules/{code}`. Los valores de abajo son los que carga `seed.py` como punto de partida.

| Código | Se activa cuando… | Peso | Parámetros por defecto |
|--------|-------------------|------|------------------------|
| `SELF_TRANSFER` | Cuenta origen = cuenta destino | **Bloqueante** (rechazo inmediato, score 100) | — |
| `HIGH_AMOUNT` | El monto supera el umbral absoluto | 30 | `threshold: 5000000` |
| `VELOCITY_COUNT` | La cuenta origen intentó más de N transacciones en una ventana corta | 35 | `max_count: 5`, `window_minutes: 10` |
| `VELOCITY_AMOUNT` | La suma de montos de la cuenta origen en la ventana supera un límite | 25 | `max_total: 10000000`, `window_minutes: 60` |
| `NEW_BENEFICIARY_HIGH_AMOUNT` | Primera vez que se envía a ese destino **y** el monto supera un umbral | 20 | `threshold: 1000000` |
| `AMOUNT_DEVIATION` | El monto es X veces mayor al promedio de los últimos 30 días de la cuenta | 25 | `multiplier: 5`, `lookback_days: 30`, `min_history: 3` |
| `UNUSUAL_HOUR` | La transacción ocurre en horario de madrugada (zona horaria configurada) | 10 | `start_hour: 0`, `end_hour: 5` |

> `AMOUNT_DEVIATION` requiere un mínimo de historial (`min_history`); con cuentas nuevas no se activa para evitar falsos positivos.
> Los montos están expresados en la moneda base del sistema (COP por defecto).

### Cálculo del score y la decisión

```
riskScore = min(100, suma de pesos de las reglas activadas)

Si se activó una regla bloqueante  →  REJECTED (riskScore = 100)
Si riskScore >= REJECT_THRESHOLD   →  REJECTED   (por defecto 70)
En otro caso                       →  APPROVED
```

**Ejemplo:** transferencia de madrugada (10) + a un beneficiario nuevo con monto alto (20) + monto 6× el promedio (25) + muchas transacciones seguidas (35) = **90 → `REJECTED`**.
Solo madrugada + beneficiario nuevo = **30 → `APPROVED`**.

### Cómo agregar una regla nueva

1. Crear `rules/mi_regla.py` implementando la interfaz `Rule` de `rules/base.py`.
2. Registrarla en `rules/registry.py`.
3. Agregar su fila por defecto en `db/seed.py` (o insertarla con una migración).
4. Escribir `tests/unit/rules/test_mi_regla.py`.

No hay que modificar ningún otro microservicio.

---

## 🗄️ Modelo de Base de Datos

**Tabla: `fraud_evaluations`**

```
┌──────────────────────────┬──────────────────┬──────────────────────────────────────────────────┐
│ Columna                  │ Tipo             │ Descripción                                       │
├──────────────────────────┼──────────────────┼──────────────────────────────────────────────────┤
│ id                       │ UUID (PK)        │ Identificador de la evaluación                    │
│ transaction_id           │ VARCHAR(64) UQ   │ ID de la transacción — clave de idempotencia      │
│ user_id                  │ UUID             │ Usuario que origina el pago (referencia lógica)   │
│ source_account_id        │ UUID             │ Cuenta origen                                     │
│ destination_account_id   │ UUID             │ Cuenta destino                                    │
│ amount                   │ DECIMAL(19,4)    │ Monto de la transacción                           │
│ currency                 │ VARCHAR(3)       │ Moneda (ISO 4217)                                 │
│ risk_score               │ SMALLINT         │ 0–100                                             │
│ decision                 │ VARCHAR(20)      │ ENUM: APPROVED | REJECTED                         │
│ triggered_rules          │ JSONB            │ [{code, weight, reason}]                          │
│ rules_snapshot_version   │ VARCHAR(20)      │ Versión de configuración de reglas usada          │
│ requested_at             │ TIMESTAMPTZ      │ Momento en que se originó la transacción          │
│ evaluated_at             │ TIMESTAMPTZ      │ Momento en que se emitió la decisión              │
└──────────────────────────┴──────────────────┴──────────────────────────────────────────────────┘
Índices: UNIQUE(transaction_id) · (source_account_id, requested_at) · (source_account_id, destination_account_id)
```

**Tabla: `fraud_rules`**

```
┌──────────────────┬──────────────────┬──────────────────────────────────────────────────┐
│ Columna          │ Tipo             │ Descripción                                       │
├──────────────────┼──────────────────┼──────────────────────────────────────────────────┤
│ id               │ UUID (PK)        │ Identificador                                     │
│ code             │ VARCHAR(50) UQ   │ Código de la regla (ej: HIGH_AMOUNT)              │
│ description      │ VARCHAR(255)     │ Descripción legible                               │
│ weight           │ SMALLINT         │ Puntos que suma al activarse                      │
│ blocking         │ BOOLEAN          │ Si es true, rechaza sin importar el score         │
│ params           │ JSONB            │ Umbrales y ventanas específicos de la regla       │
│ enabled          │ BOOLEAN          │ Regla activa / desactivada                        │
│ updated_at       │ TIMESTAMPTZ      │ Última modificación                               │
└──────────────────┴──────────────────┴──────────────────────────────────────────────────┘
```

> ⚠️ `fraud-engine` tiene su **propia instancia de PostgreSQL** aislada (`fraud-db`). Ningún otro microservicio accede a esta base de datos directamente. Las referencias a usuarios y cuentas son únicamente lógicas (UUIDs).

> ℹ️ Las velocidades y promedios se calculan **solo sobre las transacciones que el propio motor ha evaluado**. Las reglas de velocidad cuentan todos los intentos (aprobados o rechazados); las de promedio y beneficiario conocido consideran solo los `APPROVED`.

---

## 📨 Eventos Kafka

### Evento consumido

**Topic:** `fraud.check-requested` · **Key:** `transactionId` · **Productor:** `payment-orchestrator`

```json
{
  "transactionId": "txn-9f1e2a3b-7c4d-4e5f-8a9b-0c1d2e3f4a5b",
  "userId": "550e8400-e29b-41d4-a716-446655440000",
  "sourceAccountId": "4c5d6e7f-1111-2222-3333-444455556666",
  "destinationAccountId": "7a8b9c0d-aaaa-bbbb-cccc-ddddeeeeffff",
  "amount": 500000.00,
  "currency": "COP",
  "timestamp": "2025-01-15T10:31:00Z"
}
```

### Evento publicado

**Topic:** `fraud.check-completed` · **Key:** `transactionId` · **Consumidor:** `payment-orchestrator`

```json
{
  "transactionId": "txn-9f1e2a3b-7c4d-4e5f-8a9b-0c1d2e3f4a5b",
  "decision": "REJECTED",
  "riskScore": 90,
  "triggeredRules": [
    { "code": "VELOCITY_COUNT",  "weight": 35, "reason": "8 transacciones en 10 minutos (máx. 5)" },
    { "code": "AMOUNT_DEVIATION","weight": 25, "reason": "Monto 6.2x superior al promedio de 30 días" },
    { "code": "NEW_BENEFICIARY_HIGH_AMOUNT", "weight": 20, "reason": "Primer envío a este destino con monto alto" },
    { "code": "UNUSUAL_HOUR",    "weight": 10, "reason": "Transacción a las 02:14 (America/Bogota)" }
  ],
  "evaluatedAt": "2025-01-15T10:31:00.120Z"
}
```

`decision` puede ser `APPROVED` o `REJECTED`. Si es `APPROVED`, el orquestador continúa con la reserva de fondos; si es `REJECTED`, la transacción termina sin haber tocado ningún saldo.

### Dead Letter Queue

**Topic:** `fraud.check-requested.dlq` — mensajes que no se pudieron deserializar o validar (JSON inválido, campos faltantes, montos negativos). Se conservan con su cabecera de error para diagnóstico.

---

## 🔁 Idempotencia y Tolerancia a Fallos

Kafka garantiza entrega *al menos una vez*, por lo que el mismo mensaje puede llegar duplicado.

- **Idempotencia:** `transaction_id` es único en `fraud_evaluations`. Si llega un `fraud.check-requested` ya evaluado, el servicio **no reevalúa**: reenvía la misma decisión guardada. Así el historial no se contamina con duplicados.
- **Commit de offset tardío:** el offset se confirma solo después de persistir y publicar. Si el servicio cae a la mitad, el mensaje se reprocesa sin efectos secundarios.
- **Mensajes inválidos:** van a la DLQ sin bloquear la partición.
- **Si `fraud-engine` está caído:** los mensajes se acumulan en Kafka y se procesan al volver. Mientras tanto el `payment-orchestrator` aplica un **timeout** y rechaza la transacción (*fail-closed*: ante la duda, el dinero no se mueve). Como el chequeo ocurre antes de reservar fondos, no hay nada que compensar.
- **Regla defectuosa:** si una regla lanza una excepción, se registra el error, se marca esa regla como omitida en el resultado y se continúa con las demás (una regla rota no debe tumbar todo el motor).

---

## 🧪 Pruebas

El servicio incluye **pruebas unitarias y de integración** desde su primera versión.

### Pruebas unitarias (`tests/unit/`)
Rápidas, sin infraestructura externa.

| Qué se prueba | Enfoque |
|---------------|---------|
| Cada regla | Casos de borde: justo debajo, justo en y justo encima del umbral; regla desactivada; sin historial suficiente |
| `RiskScorer` | Suma de pesos, tope en 100, umbral de rechazo, regla bloqueante que ignora el score |
| `FeatureBuilder` | Cálculo de conteos, sumas y promedios con un repositorio falso |
| `FraudEvaluationService` | Flujo completo con repositorios y producer simulados: transacción aprobada, rechazada, duplicada, regla que falla |
| `RuleRegistry` | Construcción de reglas desde configuración; código desconocido |

### Pruebas de integración (`tests/integration/`)
Usan **Testcontainers** con PostgreSQL y Kafka reales.

| Qué se prueba | Enfoque |
|---------------|---------|
| Consultas de historial | Ventanas de tiempo y agregaciones contra PostgreSQL real |
| Flujo Kafka de extremo a extremo | Publicar `fraud.check-requested` → recibir `fraud.check-completed` con la decisión esperada |
| Idempotencia | Enviar dos veces el mismo `transactionId` → un solo registro y la misma respuesta |
| API HTTP | Endpoints de reglas y evaluaciones, incluyendo rechazo sin API key (401) |

### Ejecución

```bash
# Solo unitarias (rápidas)
pytest tests/unit

# Integración (requiere Docker en ejecución)
pytest tests/integration

# Todo, con reporte de cobertura (objetivo mínimo: 85%)
pytest --cov=app --cov-report=term-missing --cov-fail-under=85
```

---

## 📦 Dependencias

| Dependencia | Uso |
|-------------|-----|
| `fastapi` | Framework web, validación y OpenAPI automático |
| `uvicorn[standard]` | Servidor ASGI |
| `pydantic` (v2) / `pydantic-settings` | Contratos de datos y configuración |
| `sqlalchemy[asyncio]` (2.x) | ORM asíncrono |
| `asyncpg` | Driver asíncrono de PostgreSQL |
| `alembic` | Migraciones de base de datos |
| `aiokafka` | Consumer y producer asíncronos de Kafka |

**Desarrollo y pruebas:**

| Dependencia | Uso |
|-------------|-----|
| `pytest` · `pytest-asyncio` | Ejecución de pruebas, incluyendo código asíncrono |
| `pytest-cov` | Cobertura |
| `httpx` | Cliente HTTP asíncrono para probar la API |
| `testcontainers` | PostgreSQL y Kafka efímeros para integración |
| `ruff` | Linter y formateador |

**Versión de Python:** 3.14.7

---

## ⚙️ Variables de Entorno

```python
# app/core/config.py  (pydantic-settings)
class Settings(BaseSettings):
    app_port: int = 8085
    database_url: str                      # postgresql+asyncpg://user:pass@fraud-db:5432/fraud_db
    kafka_broker: str                      # kafka:9092
    kafka_group_id: str = "fraud-engine-group"
    topic_check_requested: str = "fraud.check-requested"
    topic_check_completed: str = "fraud.check-completed"
    topic_dlq: str = "fraud.check-requested.dlq"
    internal_api_key: str                  # protege /fraud/**
    reject_threshold: int = 70             # score >= umbral => REJECTED
    timezone: str = "America/Bogota"       # para la regla UNUSUAL_HOUR
    log_level: str = "INFO"
```

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `DATABASE_URL` | Conexión a PostgreSQL | `postgresql+asyncpg://fraud_user:s3cr3t@fraud-db:5432/fraud_db` |
| `KAFKA_BROKER` | Host y puerto de Kafka | `kafka:9092` |
| `INTERNAL_API_KEY` | Clave para los endpoints administrativos | `change-me` |
| `REJECT_THRESHOLD` | Score mínimo para rechazar | `70` |
| `TIMEZONE` | Zona horaria para reglas de horario | `America/Bogota` |

---

## 🐳 Dockerfile

```dockerfile
FROM python:3.14.7-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8085
# Aplica migraciones y arranca el servicio
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8085"]
```

---

## 🔄 Flujo Interno: Evaluación de una Transacción

```
Kafka [fraud.check-requested]
        │
        ▼
consumer.on_message()
        ├── Deserializa y valida con Pydantic → si falla: DLQ
        ▼
FraudEvaluationService.evaluate()
        ├── ¿Existe evaluación para este transactionId?
        │       └── Sí → reenvía la decisión guardada (idempotencia) y termina
        ├── FeatureBuilder: consulta historial (conteos, sumas, promedio, beneficiario conocido)
        ├── Carga reglas activas desde fraud_rules
        ├── Ejecuta cada regla → lista de RuleResult
        ├── RiskScorer: suma pesos, aplica regla bloqueante y umbral → decisión
        ├── Persiste FraudEvaluation en PostgreSQL
        └── producer.publish_completed() → Kafka [fraud.check-completed]
        │
        ▼
Confirma offset (commit)
```

---

## 🚀 Evolución hacia Machine Learning

Cuando exista un dataset etiquetado, el camino previsto es:

1. Las evaluaciones guardadas en `fraud_evaluations` (con reglas activadas y, más adelante, la etiqueta real de fraude confirmado) sirven como base de entrenamiento.
2. Se entrena un modelo fuera de línea y se expone dentro de este mismo servicio como una **regla más** (`MlModelRule`) que aporta un score.
3. Se ejecuta primero en **modo sombra** (calcula pero no decide) para comparar contra las reglas.
4. Si rinde mejor, se le otorga peso en la decisión final.

Los contratos Kafka (`fraud.check-requested` / `fraud.check-completed`) no cambian: ni el `payment-orchestrator` ni ningún otro servicio se enteran del cambio interno.

---

*`fraud-engine` — Porque el mejor momento para detener un fraude es antes de que el dinero se mueva.*# 🛡️ fraud-engine — El Motor de Detección de Fraude

> Microservicio de FinNode responsable de evaluar el riesgo de cada transacción **antes** de que el dinero sea reservado. Está construido en **Python + FastAPI**, funciona con un **motor de reglas ponderadas** (sin modelo de Machine Learning entrenado) y se comunica con el resto del sistema **exclusivamente mediante Kafka**.

---

## 📋 Tabla de Contenidos

- [Responsabilidades](#-responsabilidades)
- [¿Por qué reglas y no Machine Learning?](#-por-qué-reglas-y-no-machine-learning)
- [Cómo se comunica con el sistema](#-cómo-se-comunica-con-el-sistema)
- [Endpoints](#-endpoints)
- [Estructura de Carpetas](#-estructura-de-carpetas)
- [Descripción de Cada Capa](#-descripción-de-cada-capa)
- [Motor de Reglas](#-motor-de-reglas)
- [Modelo de Base de Datos](#-modelo-de-base-de-datos)
- [Eventos Kafka](#-eventos-kafka)
- [Idempotencia y Tolerancia a Fallos](#-idempotencia-y-tolerancia-a-fallos)
- [Pruebas](#-pruebas)
- [Dependencias](#-dependencias)
- [Variables de Entorno](#-variables-de-entorno)
- [Dockerfile](#-dockerfile)
- [Flujo Interno](#-flujo-interno-evaluación-de-una-transacción)
- [Evolución hacia Machine Learning](#-evolución-hacia-machine-learning)

---

## ✅ Responsabilidades

| # | Responsabilidad | Descripción |
|---|----------------|-------------|
| 1 | **Evaluar riesgo** | Consume `fraud.check-requested`, ejecuta el conjunto de reglas activas y calcula un `riskScore` entre 0 y 100 |
| 2 | **Decidir** | Convierte el score en una decisión: `APPROVED` o `REJECTED` |
| 3 | **Responder** | Publica `fraud.check-completed` con la decisión, el score y las reglas que se activaron |
| 4 | **Auditar** | Persiste cada evaluación en PostgreSQL (quién, cuánto, qué reglas, qué decisión) para trazabilidad y análisis posterior |
| 5 | **Mantener historial** | Su propia tabla de evaluaciones alimenta las reglas de comportamiento (velocidad, monto promedio, beneficiario nuevo) |
| 6 | **Administrar reglas** | Permite consultar y ajustar pesos, umbrales y activación de reglas sin redesplegar código |

---

## 🧠 ¿Por qué reglas y no Machine Learning?

Este servicio **no utiliza un modelo entrenado**: es un sistema de scoring basado en reglas.

- No existe (todavía) un dataset etiquetado de fraude para entrenar un modelo.
- Un motor de reglas es **explicable**: cada rechazo indica exactamente qué reglas se activaron, algo indispensable en un entorno bancario y regulatorio.
- A diferencia de reglas estáticas "todo o nada", aquí las reglas se **ponderan**, usan **señales de comportamiento** (velocidad, desviación del promedio, beneficiario nuevo) y son **configurables en base de datos**.
- La arquitectura separa `reglas → score → decisión`, de modo que en el futuro un modelo de ML pueda añadirse como una regla más (ver [Evolución hacia Machine Learning](#-evolución-hacia-machine-learning)) sin tocar al resto de microservicios.

---

## 📡 Cómo se comunica con el sistema

`fraud-engine` **no expone ningún endpoint de negocio** y **nadie lo llama por HTTP** para evaluar un pago. Todo ocurre por Kafka:

```
payment-orchestrator                     fraud-engine
        │                                     │
        │── fraud.check-requested ───────────▶│  (1) consume, evalúa reglas, guarda evaluación
        │                                     │
        │◀─────────── fraud.check-completed ──│  (2) publica decisión + score + reglas activadas
```

- El `payment-orchestrator` es el **único productor** de `fraud.check-requested` y el **único consumidor** de `fraud.check-completed`.
- La clave (key) de cada mensaje es el `transactionId`, lo que garantiza orden por transacción y permite correlacionar petición y respuesta.
- El servicio tampoco se expone en el `api-gateway`. Su API HTTP es solo de **salud y administración**, accesible dentro de la red interna de Docker.

---

## 🌐 Endpoints

```
GET   /health                                → Estado del servicio (DB y Kafka)
GET   /fraud/evaluations/{transactionId}     → Detalle de una evaluación (auditoría)
GET   /fraud/evaluations                     → Listado paginado (filtros: accountId, decision, from, to)
GET   /fraud/rules                           → Lista de reglas con peso, parámetros y estado
PATCH /fraud/rules/{code}                    → Ajustar peso, parámetros o activar/desactivar una regla
GET   /docs                                  → Documentación OpenAPI (Swagger UI, generada por FastAPI)
```

> 🔒 Los endpoints `/fraud/**` son **administrativos e internos**: se protegen con la cabecera `X-Internal-Api-Key` y no se enrutan desde el `api-gateway`.

---

## 📁 Estructura de Carpetas

```
fraud-engine/
├── app/
│   ├── main.py                                  ← Punto de entrada FastAPI (lifespan: arranca/para consumer y producer)
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                            ← Settings con pydantic-settings (variables de entorno)
│   │   └── logging.py                           ← Logging estructurado (JSON) con transactionId en cada línea
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py                              ← Dependencias: sesión de DB, validación de API key interna
│   │   ├── health.py                            ← GET /health
│   │   ├── evaluations.py                       ← Consulta de evaluaciones
│   │   └── rules.py                             ← Consulta y ajuste de reglas
│   │
│   ├── schemas/                                 ← Modelos Pydantic (contratos HTTP y Kafka)
│   │   ├── __init__.py
│   │   ├── common.py                            ← Esquemas compartidos (paginación, enums, tipos comunes)
│   │   ├── events.py                            ← FraudCheckRequested, FraudCheckCompleted
│   │   ├── evaluation.py                        ← EvaluationResponse, EvaluationFilter, Page
│   │   └── rule.py                              ← RuleResponse, RuleUpdateRequest
│   │
│   ├── models/                                  ← Entidades SQLAlchemy 2.0
│   │   ├── init.py                              ← Importa los modelos para que Alembic los detecte
│   │   ├── base.py                              ← DeclarativeBase
│   │   ├── fraud_evaluation.py                  ← Tabla fraud_evaluations
│   │   └── fraud_rule.py                        ← Tabla fraud_rules
│   │
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── evaluation_repository.py             ← Guardar/consultar evaluaciones + consultas de historial
│   │   └── rule_repository.py                   ← Cargar reglas activas, actualizar configuración
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── fraud_evaluation_service.py          ← Orquesta: idempotencia → features → reglas → score → persistir → publicar
│   │   ├── feature_builder.py                   ← Calcula señales de historial (conteo, suma, promedio, beneficiario conocido)
│   │   ├── risk_scorer.py                       ← Suma pesos, aplica tope 100 y umbral de decisión
│   │   └── rule_admin_service.py                ← Lógica de administración de reglas
│   │
│   ├── rules/                                   ← Cada regla es una clase pura, sin acceso a DB ni Kafka
│   │   ├── __init__.py
│   │   ├── base.py                              ← Interfaz Rule, RuleContext, RuleResult
│   │   ├── helpers.py                           ← Funciones auxiliares compartidas por las reglas
│   │   ├── registry.py                          ← Mapa código → clase de regla; construye reglas desde la config de DB
│   │   ├── high_amount.py                       ← HIGH_AMOUNT
│   │   ├── velocity_count.py                    ← VELOCITY_COUNT
│   │   ├── velocity_amount.py                   ← VELOCITY_AMOUNT
│   │   ├── new_beneficiary.py                   ← NEW_BENEFICIARY_HIGH_AMOUNT
│   │   ├── amount_deviation.py                  ← AMOUNT_DEVIATION
│   │   ├── unusual_hour.py                      ← UNUSUAL_HOUR
│   │   └── self_transfer.py                     ← SELF_TRANSFER (regla bloqueante)
│   │
│   ├── kafka/
│   │   ├── __init__.py
│   │   ├── consumer.py                          ← Loop aiokafka: escucha fraud.check-requested, maneja errores y DLQ
│   │   └── producer.py                          ← Publica fraud.check-completed
│   │
│   └── db/
│       ├── __init__.py
│       ├── session.py                           ← Engine y sessionmaker async (SQLAlchemy + asyncpg)
│       └── seed.py                              ← Reglas por defecto (se insertan si la tabla está vacía)
│
├── alembic/
│   ├── env.py
│   ├── script.py
│   └── versions/                                ← Migraciones de esquema (ddl controlado, no auto-create)
│
├── tests/
│   ├── conftest.py                              ← Fixtures compartidas (contexto de ejemplo, fakes)
│   ├── unit/
│   │   ├── rules/                               ← Un archivo de test por regla
│   │   │   ├── test_high_amount.py
│   │   │   ├── test_velocity_count.py
│   │   │   ├── test_velocity_amount.py
│   │   │   ├── test_new_beneficiary.py
│   │   │   ├── test_amount_deviation.py
│   │   │   ├── test_unusual_hour.py
│   │   │   └── test_self_transfer.py
│   │   ├── test_risk_scorer.py                  ← Suma, tope 100, umbral, regla bloqueante
│   │   ├── test_feature_builder.py              ← Cálculo de señales con repositorio falso
│   │   ├── test_fraud_evaluation_service.py     ← Orquestación con repos y producer simulados (mocks)
│   │   └── test_rule_registry.py                ← Construcción de reglas desde configuración
│   └── integration/
│       ├── conftest.py                          ← Testcontainers: PostgreSQL + Kafka reales
│       ├── test_evaluation_repository.py        ← Consultas de historial contra PostgreSQL real
│       ├── test_kafka_flow.py                   ← Publicar check-requested → recibir check-completed
│       ├── test_idempotency.py                  ← Mismo transactionId dos veces = misma respuesta, 1 registro
│       └── test_api.py                          ← Endpoints con httpx.AsyncClient
│
├── alembic.ini
├── pyproject.toml                               ← Dependencias, configuración de pytest, ruff y coverage
├── uv.lock                                      ← Versiones exactas de dependencias
├── requirements.txt
├── README.md
├── fraud-engine-README.md                       ← Este documento
└── Dockerfile                                   ← Imagen Docker del servicio
```

---

## 📐 Descripción de Cada Capa

### `core/`
| Módulo | Qué hace |
|--------|----------|
| `config.py` | Clase `Settings` (pydantic-settings) que carga toda la configuración desde variables de entorno. Un solo lugar, tipado y validado al arrancar |
| `logging.py` | Logging en JSON; cada evaluación registra `transactionId`, `riskScore` y `decision` para poder rastrearla |

### `api/`
Capa HTTP mínima. No contiene lógica de negocio; solo valida entrada, llama a los servicios y devuelve respuestas.

### `schemas/`
Modelos Pydantic v2. Definen y validan los contratos tanto HTTP como de mensajes Kafka. Un mensaje malformado falla aquí y se envía a la DLQ.

### `models/` y `repositories/`
Entidades SQLAlchemy y acceso a datos. Los repositorios también exponen las consultas de historial que necesitan las reglas (por ejemplo: "cuántas transacciones hizo esta cuenta en los últimos 10 minutos").

### `services/`
| Clase | Qué hace |
|-------|----------|
| `FraudEvaluationService` | Flujo completo de una evaluación (ver [Flujo Interno](#-flujo-interno-evaluación-de-una-transacción)) |
| `FeatureBuilder` | Consulta el historial una sola vez y arma un objeto de señales (`RuleContext`) que reciben todas las reglas |
| `RiskScorer` | Combina resultados de reglas en un score y decide `APPROVED` / `REJECTED` |
| `RuleAdminService` | Actualiza reglas y valida que pesos y parámetros sean coherentes |

### `rules/`
Corazón del motor. Cada regla recibe un `RuleContext` (transacción + señales de historial) y devuelve un `RuleResult(triggered, weight, reason)`. **No hacen I/O**, por lo que se prueban con pruebas unitarias puras y rápidas.

### `kafka/`
Consumer y producer con `aiokafka`. El consumer corre como tarea de fondo dentro del ciclo de vida (`lifespan`) de FastAPI; el commit del offset se hace **después** de persistir y publicar el resultado (at-least-once + idempotencia).

---

## ⚖️ Motor de Reglas

### Reglas por defecto

Todos los valores son **configurables** en la tabla `fraud_rules` (columna `params`) y ajustables vía `PATCH /fraud/rules/{code}`. Los valores de abajo son los que carga `seed.py` como punto de partida.

| Código | Se activa cuando… | Peso | Parámetros por defecto |
|--------|-------------------|------|------------------------|
| `SELF_TRANSFER` | Cuenta origen = cuenta destino | **Bloqueante** (rechazo inmediato, score 100) | — |
| `HIGH_AMOUNT` | El monto supera el umbral absoluto | 30 | `threshold: 5000000` |
| `VELOCITY_COUNT` | La cuenta origen intentó más de N transacciones en una ventana corta | 35 | `max_count: 5`, `window_minutes: 10` |
| `VELOCITY_AMOUNT` | La suma de montos de la cuenta origen en la ventana supera un límite | 25 | `max_total: 10000000`, `window_minutes: 60` |
| `NEW_BENEFICIARY_HIGH_AMOUNT` | Primera vez que se envía a ese destino **y** el monto supera un umbral | 20 | `threshold: 1000000` |
| `AMOUNT_DEVIATION` | El monto es X veces mayor al promedio de los últimos 30 días de la cuenta | 25 | `multiplier: 5`, `lookback_days: 30`, `min_history: 3` |
| `UNUSUAL_HOUR` | La transacción ocurre en horario de madrugada (zona horaria configurada) | 10 | `start_hour: 0`, `end_hour: 5` |

> `AMOUNT_DEVIATION` requiere un mínimo de historial (`min_history`); con cuentas nuevas no se activa para evitar falsos positivos.
> Los montos están expresados en la moneda base del sistema (COP por defecto).

### Cálculo del score y la decisión

```
riskScore = min(100, suma de pesos de las reglas activadas)

Si se activó una regla bloqueante  →  REJECTED (riskScore = 100)
Si riskScore >= REJECT_THRESHOLD   →  REJECTED   (por defecto 70)
En otro caso                       →  APPROVED
```

**Ejemplo:** transferencia de madrugada (10) + a un beneficiario nuevo con monto alto (20) + monto 6× el promedio (25) + muchas transacciones seguidas (35) = **90 → `REJECTED`**.
Solo madrugada + beneficiario nuevo = **30 → `APPROVED`**.

### Cómo agregar una regla nueva

1. Crear `rules/mi_regla.py` implementando la interfaz `Rule` de `rules/base.py`.
2. Registrarla en `rules/registry.py`.
3. Agregar su fila por defecto en `db/seed.py` (o insertarla con una migración).
4. Escribir `tests/unit/rules/test_mi_regla.py`.

No hay que modificar ningún otro microservicio.

---

## 🗄️ Modelo de Base de Datos

**Tabla: `fraud_evaluations`**

```
┌──────────────────────────┬──────────────────┬──────────────────────────────────────────────────┐
│ Columna                  │ Tipo             │ Descripción                                       │
├──────────────────────────┼──────────────────┼──────────────────────────────────────────────────┤
│ id                       │ UUID (PK)        │ Identificador de la evaluación                    │
│ transaction_id           │ VARCHAR(64) UQ   │ ID de la transacción — clave de idempotencia      │
│ user_id                  │ UUID             │ Usuario que origina el pago (referencia lógica)   │
│ source_account_id        │ UUID             │ Cuenta origen                                     │
│ destination_account_id   │ UUID             │ Cuenta destino                                    │
│ amount                   │ DECIMAL(19,4)    │ Monto de la transacción                           │
│ currency                 │ VARCHAR(3)       │ Moneda (ISO 4217)                                 │
│ risk_score               │ SMALLINT         │ 0–100                                             │
│ decision                 │ VARCHAR(20)      │ ENUM: APPROVED | REJECTED                         │
│ triggered_rules          │ JSONB            │ [{code, weight, reason}]                          │
│ rules_snapshot_version   │ VARCHAR(20)      │ Versión de configuración de reglas usada          │
│ requested_at             │ TIMESTAMPTZ      │ Momento en que se originó la transacción          │
│ evaluated_at             │ TIMESTAMPTZ      │ Momento en que se emitió la decisión              │
└──────────────────────────┴──────────────────┴──────────────────────────────────────────────────┘
Índices: UNIQUE(transaction_id) · (source_account_id, requested_at) · (source_account_id, destination_account_id)
```

**Tabla: `fraud_rules`**

```
┌──────────────────┬──────────────────┬──────────────────────────────────────────────────┐
│ Columna          │ Tipo             │ Descripción                                       │
├──────────────────┼──────────────────┼──────────────────────────────────────────────────┤
│ id               │ UUID (PK)        │ Identificador                                     │
│ code             │ VARCHAR(50) UQ   │ Código de la regla (ej: HIGH_AMOUNT)              │
│ description      │ VARCHAR(255)     │ Descripción legible                               │
│ weight           │ SMALLINT         │ Puntos que suma al activarse                      │
│ blocking         │ BOOLEAN          │ Si es true, rechaza sin importar el score         │
│ params           │ JSONB            │ Umbrales y ventanas específicos de la regla       │
│ enabled          │ BOOLEAN          │ Regla activa / desactivada                        │
│ updated_at       │ TIMESTAMPTZ      │ Última modificación                               │
└──────────────────┴──────────────────┴──────────────────────────────────────────────────┘
```

> ⚠️ `fraud-engine` tiene su **propia instancia de PostgreSQL** aislada (`fraud-db`). Ningún otro microservicio accede a esta base de datos directamente. Las referencias a usuarios y cuentas son únicamente lógicas (UUIDs).

> ℹ️ Las velocidades y promedios se calculan **solo sobre las transacciones que el propio motor ha evaluado**. Las reglas de velocidad cuentan todos los intentos (aprobados o rechazados); las de promedio y beneficiario conocido consideran solo los `APPROVED`.

---

## 📨 Eventos Kafka

### Evento consumido

**Topic:** `fraud.check-requested` · **Key:** `transactionId` · **Productor:** `payment-orchestrator`

```json
{
  "transactionId": "txn-9f1e2a3b-7c4d-4e5f-8a9b-0c1d2e3f4a5b",
  "userId": "550e8400-e29b-41d4-a716-446655440000",
  "sourceAccountId": "4c5d6e7f-1111-2222-3333-444455556666",
  "destinationAccountId": "7a8b9c0d-aaaa-bbbb-cccc-ddddeeeeffff",
  "amount": 500000.00,
  "currency": "COP",
  "timestamp": "2025-01-15T10:31:00Z"
}
```

### Evento publicado

**Topic:** `fraud.check-completed` · **Key:** `transactionId` · **Consumidor:** `payment-orchestrator`

```json
{
  "transactionId": "txn-9f1e2a3b-7c4d-4e5f-8a9b-0c1d2e3f4a5b",
  "decision": "REJECTED",
  "riskScore": 90,
  "triggeredRules": [
    { "code": "VELOCITY_COUNT",  "weight": 35, "reason": "8 transacciones en 10 minutos (máx. 5)" },
    { "code": "AMOUNT_DEVIATION","weight": 25, "reason": "Monto 6.2x superior al promedio de 30 días" },
    { "code": "NEW_BENEFICIARY_HIGH_AMOUNT", "weight": 20, "reason": "Primer envío a este destino con monto alto" },
    { "code": "UNUSUAL_HOUR",    "weight": 10, "reason": "Transacción a las 02:14 (America/Bogota)" }
  ],
  "evaluatedAt": "2025-01-15T10:31:00.120Z"
}
```

`decision` puede ser `APPROVED` o `REJECTED`. Si es `APPROVED`, el orquestador continúa con la reserva de fondos; si es `REJECTED`, la transacción termina sin haber tocado ningún saldo.

### Dead Letter Queue

**Topic:** `fraud.check-requested.dlq` — mensajes que no se pudieron deserializar o validar (JSON inválido, campos faltantes, montos negativos). Se conservan con su cabecera de error para diagnóstico.

---

## 🔁 Idempotencia y Tolerancia a Fallos

Kafka garantiza entrega *al menos una vez*, por lo que el mismo mensaje puede llegar duplicado.

- **Idempotencia:** `transaction_id` es único en `fraud_evaluations`. Si llega un `fraud.check-requested` ya evaluado, el servicio **no reevalúa**: reenvía la misma decisión guardada. Así el historial no se contamina con duplicados.
- **Commit de offset tardío:** el offset se confirma solo después de persistir y publicar. Si el servicio cae a la mitad, el mensaje se reprocesa sin efectos secundarios.
- **Mensajes inválidos:** van a la DLQ sin bloquear la partición.
- **Si `fraud-engine` está caído:** los mensajes se acumulan en Kafka y se procesan al volver. Mientras tanto el `payment-orchestrator` aplica un **timeout** y rechaza la transacción (*fail-closed*: ante la duda, el dinero no se mueve). Como el chequeo ocurre antes de reservar fondos, no hay nada que compensar.
- **Regla defectuosa:** si una regla lanza una excepción, se registra el error, se marca esa regla como omitida en el resultado y se continúa con las demás (una regla rota no debe tumbar todo el motor).

---

## 🧪 Pruebas

El servicio incluye **pruebas unitarias y de integración** desde su primera versión.

### Pruebas unitarias (`tests/unit/`)
Rápidas, sin infraestructura externa.

| Qué se prueba | Enfoque |
|---------------|---------|
| Cada regla | Casos de borde: justo debajo, justo en y justo encima del umbral; regla desactivada; sin historial suficiente |
| `RiskScorer` | Suma de pesos, tope en 100, umbral de rechazo, regla bloqueante que ignora el score |
| `FeatureBuilder` | Cálculo de conteos, sumas y promedios con un repositorio falso |
| `FraudEvaluationService` | Flujo completo con repositorios y producer simulados: transacción aprobada, rechazada, duplicada, regla que falla |
| `RuleRegistry` | Construcción de reglas desde configuración; código desconocido |

### Pruebas de integración (`tests/integration/`)
Usan **Testcontainers** con PostgreSQL y Kafka reales.

| Qué se prueba | Enfoque |
|---------------|---------|
| Consultas de historial | Ventanas de tiempo y agregaciones contra PostgreSQL real |
| Flujo Kafka de extremo a extremo | Publicar `fraud.check-requested` → recibir `fraud.check-completed` con la decisión esperada |
| Idempotencia | Enviar dos veces el mismo `transactionId` → un solo registro y la misma respuesta |
| API HTTP | Endpoints de reglas y evaluaciones, incluyendo rechazo sin API key (401) |

### Ejecución

```bash
# Solo unitarias (rápidas)
pytest tests/unit

# Integración (requiere Docker en ejecución)
pytest tests/integration

# Todo, con reporte de cobertura (objetivo mínimo: 85%)
pytest --cov=app --cov-report=term-missing --cov-fail-under=85
```

---

## 📦 Dependencias

| Dependencia | Uso |
|-------------|-----|
| `fastapi` | Framework web, validación y OpenAPI automático |
| `uvicorn[standard]` | Servidor ASGI |
| `pydantic` (v2) / `pydantic-settings` | Contratos de datos y configuración |
| `sqlalchemy[asyncio]` (2.x) | ORM asíncrono |
| `asyncpg` | Driver asíncrono de PostgreSQL |
| `alembic` | Migraciones de base de datos |
| `aiokafka` | Consumer y producer asíncronos de Kafka |

**Desarrollo y pruebas:**

| Dependencia | Uso |
|-------------|-----|
| `pytest` · `pytest-asyncio` | Ejecución de pruebas, incluyendo código asíncrono |
| `pytest-cov` | Cobertura |
| `httpx` | Cliente HTTP asíncrono para probar la API |
| `testcontainers` | PostgreSQL y Kafka efímeros para integración |
| `ruff` | Linter y formateador |

**Versión de Python:** 3.14.7

---

## ⚙️ Variables de Entorno

```python
# app/core/config.py  (pydantic-settings)
class Settings(BaseSettings):
    app_port: int = 8085
    database_url: str                      # postgresql+asyncpg://user:pass@fraud-db:5432/fraud_db
    kafka_broker: str                      # kafka:9092
    kafka_group_id: str = "fraud-engine-group"
    topic_check_requested: str = "fraud.check-requested"
    topic_check_completed: str = "fraud.check-completed"
    topic_dlq: str = "fraud.check-requested.dlq"
    internal_api_key: str                  # protege /fraud/**
    reject_threshold: int = 70             # score >= umbral => REJECTED
    timezone: str = "America/Bogota"       # para la regla UNUSUAL_HOUR
    log_level: str = "INFO"
```

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `DATABASE_URL` | Conexión a PostgreSQL | `postgresql+asyncpg://fraud_user:s3cr3t@fraud-db:5432/fraud_db` |
| `KAFKA_BROKER` | Host y puerto de Kafka | `kafka:9092` |
| `INTERNAL_API_KEY` | Clave para los endpoints administrativos | `change-me` |
| `REJECT_THRESHOLD` | Score mínimo para rechazar | `70` |
| `TIMEZONE` | Zona horaria para reglas de horario | `America/Bogota` |

---

## 🐳 Dockerfile

```dockerfile
FROM python:3.14.7-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8085
# Aplica migraciones y arranca el servicio
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8085"]
```

---

## 🔄 Flujo Interno: Evaluación de una Transacción

```
Kafka [fraud.check-requested]
        │
        ▼
consumer.on_message()
        ├── Deserializa y valida con Pydantic → si falla: DLQ
        ▼
FraudEvaluationService.evaluate()
        ├── ¿Existe evaluación para este transactionId?
        │       └── Sí → reenvía la decisión guardada (idempotencia) y termina
        ├── FeatureBuilder: consulta historial (conteos, sumas, promedio, beneficiario conocido)
        ├── Carga reglas activas desde fraud_rules
        ├── Ejecuta cada regla → lista de RuleResult
        ├── RiskScorer: suma pesos, aplica regla bloqueante y umbral → decisión
        ├── Persiste FraudEvaluation en PostgreSQL
        └── producer.publish_completed() → Kafka [fraud.check-completed]
        │
        ▼
Confirma offset (commit)
```

---

## 🚀 Evolución hacia Machine Learning

Cuando exista un dataset etiquetado, el camino previsto es:

1. Las evaluaciones guardadas en `fraud_evaluations` (con reglas activadas y, más adelante, la etiqueta real de fraude confirmado) sirven como base de entrenamiento.
2. Se entrena un modelo fuera de línea y se expone dentro de este mismo servicio como una **regla más** (`MlModelRule`) que aporta un score.
3. Se ejecuta primero en **modo sombra** (calcula pero no decide) para comparar contra las reglas.
4. Si rinde mejor, se le otorga peso en la decisión final.

Los contratos Kafka (`fraud.check-requested` / `fraud.check-completed`) no cambian: ni el `payment-orchestrator` ni ningún otro servicio se enteran del cambio interno.

---

*`fraud-engine` — Porque el mejor momento para detener un fraude es antes de que el dinero se mueva.*

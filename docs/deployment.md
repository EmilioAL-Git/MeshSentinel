# Despliegue

## Producción (o "prod-like" local)

```bash
cp .env.example .env
docker compose up --build
```

- UI: `http://localhost:8080` (nginx sirve el frontend y hace de proxy de
  `/api` y `/ws` hacia el backend — es el único punto de entrada).
- Documentación interactiva de la API: `http://localhost:8080/api/v1/docs`.
- Las migraciones de Alembic corren automáticamente en el entrypoint del
  contenedor backend.

## Desarrollo

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

- Frontend con HMR: `http://localhost:5173`.
- Backend con recarga automática: `http://localhost:8000/api/v1/docs`.
- El override de desarrollo usa `build: !reset null` (requiere Docker
  Compose ≥2.24).

## Transporte del gateway

Variable `GATEWAY_TRANSPORT` en `.env`:

| Valor | Uso | Notas |
|---|---|---|
| `simulator` (por defecto) | Malla ficticia de 12 nodos, sin hardware | Ver `GATEWAY_SIM_SEED` / `GATEWAY_SIM_SHARED_SEED` para simular varias pasarelas viendo los mismos nodos (Multi-Gateway) |
| `usb` | Nodo conectado por puerto serie | `MESHTASTIC_USB_DEVICE` vacío = autodetección; en macOS, Docker Desktop **no** tiene acceso al puerto serie del host — hace falta correr el gateway de forma nativa (ver `docs/operations/usb.md`) |
| `tcp` | Nodo accesible por red (WiFi/Ethernet) | `GATEWAY_TCP_HOST` obligatorio. El firmware solo admite **un** cliente TCP simultáneo: cierra la app oficial si está conectada al mismo nodo |

No existe transporte `http` — solo aparece como comentario de fase futura en
`.env.example`.

Desde M5, las pasarelas también se pueden **gestionar desde la propia app**
(alta, cambio de transporte, descubrimiento, prueba de conexión) sin editar
`.env` ni reiniciar el contenedor — las variables de entorno solo definen el
arranque inicial del proceso.

## Variables de entorno relevantes

Ver `.env.example` como fuente de verdad (documenta cada variable con
comentario). Grupos principales:

- **Despliegue**: `NOC_HTTP_PORT`, `NOC_LOG_LEVEL`.
- **Base de datos**: `NOC_DATABASE_URL` (Postgres recomendado, SQLite
  soportado), `POSTGRES_*` para el contenedor.
- **Umbrales del panel de situación / alertas**: `LOW_BATTERY_THRESHOLD`,
  `OFFLINE_MINUTES_WARNING`, `OFFLINE_PERCENT_WARNING/CRITICAL`,
  `SNR_DEGRADED_THRESHOLD`, `NOC_ALERT_EVAL_INTERVAL_SECONDS`.
- **Administración remota**: `NOC_ADMIN_RATE_LIMIT_PER_MINUTE` (presupuesto
  global de la malla — hoy no está escopado por pasarela, ver
  `docs/roadmap.md`), `NOC_ADMIN_DEFAULT_TIMEOUT_SECONDS`,
  `NOC_ADMIN_MAX_ATTEMPTS`.
- **Gateway**: `GATEWAY_ID`, `GATEWAY_TRANSPORT` y las específicas de cada
  transporte (tabla arriba).

## Migraciones (manual)

```bash
cd backend
../.venv/bin/alembic upgrade head
../.venv/bin/alembic revision -m "descripcion"   # revisiones manuales
```

La URL de conexión sale de `NOC_DATABASE_URL`.

## Tests y lint

```bash
.venv/bin/python -m pytest backend/tests gateway/tests -q
.venv/bin/ruff check backend/src gateway/src backend/tests gateway/tests
cd frontend && npm run build   # incluye comprobación de tipos (tsc -b)
```

Los tests de backend están parametrizados por `NOC_TEST_DATABASE_URL`
(SQLite por defecto; en Postgres cada test usa un schema aislado).

# Fase 1 — Acceptance Test

> **Histórico**: guía escrita contra la UI anterior a v0.7 — §8 describe
> barra superior + tabla de nodos + panel de detalle lateral, sustituidos
> por StatusBar/HUD, **Flota** y el **Inspector** global. Los pasos de
> infraestructura (§1-7, §9-10) siguen siendo válidos tal cual; solo §8
> necesita traducirse a la navegación actual (ver `docs/glossary.md`). La
> funcionalidad validada no cambió.

Guía de validación manual del despliegue completo con Docker Compose usando
exclusivamente el **simulador** (sin hardware Meshtastic).

**Requisitos previos:** Docker ≥ 24 con Docker Compose ≥ 2.24, puertos 8080 libres
(y 5432/6379/8000/5173 si se usa el modo dev), `curl` y opcionalmente `jq`.

Criterio global: la fase se considera **aceptada** si los 10 puntos pasan sin
intervención manual más allá de lo descrito.

---

## 1. Arranque completo

```bash
cd meshtastic-noc
cp .env.example .env        # solo la primera vez
export GIT_COMMIT=$(git rev-parse --short HEAD)
export BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)
docker compose up --build -d
```

**Esperado:** las 5 imágenes/servicios se construyen y arrancan sin errores:
`postgres`, `redis`, `backend`, `gateway`, `frontend`.

## 2. Estado saludable de los contenedores

```bash
docker compose ps
```

**Esperado:**
- `postgres` y `redis`: `Up (healthy)`.
- `backend`: `Up (healthy)` tras ~15-30 s (su healthcheck llama a `/api/v1/health`).
- `gateway` y `frontend`: `Up`.

Si `backend` queda en `unhealthy`, ver §10 y revisar que postgres terminó su
inicialización antes del arranque (Compose ya lo ordena con `depends_on: service_healthy`).

## 3. Migraciones automáticas

```bash
docker compose logs backend | grep -A2 "Running database migrations"
```

**Esperado:**

```
Running database migrations...
INFO  [alembic.runtime.migration] Running upgrade  -> 0001, Esquema inicial: ...
```

Verificación directa del esquema:

```bash
docker compose exec postgres psql -U noc -d noc -c "\dt"
```

**Esperado:** tablas `alembic_version`, `gateways`, `nodes`, `node_positions`,
`node_telemetry`.

## 4. El simulador emite eventos

```bash
docker compose logs gateway | head -20
```

**Esperado:** `Gateway gw-01 started (transport=simulated)`.

Observación del bus en crudo (déjalo abierto ~30 s):

```bash
docker compose exec redis redis-cli subscribe noc:events
```

**Esperado:** eventos JSON con `node.seen` (ráfaga inicial), después
`telemetry.received` y `position.updated` de forma esporádica, y un
`gateway.status` (heartbeat) cada 30 s. Salir con `Ctrl+C`.

## 5. Persistencia de nodos, posiciones y telemetría

```bash
docker compose exec postgres psql -U noc -d noc -c \
  "SELECT (SELECT count(*) FROM nodes)          AS nodes,
          (SELECT count(*) FROM node_positions)  AS positions,
          (SELECT count(*) FROM node_telemetry)  AS telemetry;"
```

**Esperado:** `nodes = 12` (tamaño de la malla simulada por defecto);
`positions` y `telemetry` **crecen** al repetir la consulta tras ~30 s.
Las series son append-only: el número de filas nunca decrece.

```bash
docker compose exec postgres psql -U noc -d noc -c \
  "SELECT id, short_name, last_seen_at FROM nodes ORDER BY last_seen_at DESC LIMIT 5;"
```

**Esperado:** `last_seen_at` se actualiza con el paso del tiempo.

## 6. Endpoints REST principales

La documentación interactiva está en <http://localhost:8080/api/v1/docs>.

```bash
BASE=http://localhost:8080/api/v1

curl -s $BASE/health | jq                  # {"status":"ok", database ok, redis ok}
curl -s $BASE/system/health | jq           # añade pasarelas: gw-01 connected, stale=false
curl -s $BASE/system/version | jq          # version, git_commit, build_time
curl -s $BASE/gateways | jq                # [{"gateway_id":"gw-01","status":"connected",...}]
curl -s $BASE/nodes | jq length            # 12
NODE=$(curl -s $BASE/nodes | jq -r '.[0].node.node_id')
curl -s $BASE/nodes/$NODE | jq             # detalle con "online": true
curl -s "$BASE/nodes/$NODE/telemetry?kind=device&limit=5" | jq
curl -s "$BASE/nodes/$NODE/positions?limit=5" | jq
curl -s $BASE/nodes/%21ffffffff | jq       # nodo inexistente -> 404 {"detail":"Node not found"}
```

**Esperado:** todo 200 salvo el último (404). En `/system/version`, `git_commit`
debe coincidir con `git rev-parse --short HEAD` (si se exportó en §1) y
`events_schema_version` debe ser `1`.

## 7. WebSocket

Desde la consola del navegador (F12) en <http://localhost:8080>:

```js
const ws = new WebSocket(`ws://${location.host}/ws/events`);
ws.onmessage = (m) => console.log(JSON.parse(m.data).event_type);
```

**Esperado:** `telemetry.received` / `position.updated` apareciendo de forma
continua, y un `gateway.status` cada 30 s. Alternativa por CLI (si se dispone
de `websocat`): `websocat ws://localhost:8080/ws/events`.

## 8. Validación visual del frontend

Abrir <http://localhost:8080>:

| # | Comprobación | Esperado |
|---|---|---|
| 8.1 | Barra superior | `Nodos: 12 (12 online)`, pasarela `gw-01 connected (simulated)`, `Backend: ok` |
| 8.2 | Tabla de nodos | 12 filas con nombre (`SIM00`…), ID `!xxxxxxxx`, badge verde `online`, batería, SNR, saltos, posición (vacía en nodos sin GPS, ~25%) y «visto hace Xs» |
| 8.3 | Actualización automática | sin recargar, «visto hace» y batería cambian en <1 min (eventos WS + refetch) |
| 8.4 | Panel de detalle | clic en una fila abre el panel: identidad, hardware, firmware 2.7.0, telemetría y última posición; el botón ✕ lo cierra |
| 8.5 | Nodo sin GPS | su detalle muestra «Sin posiciones registradas…» en lugar de error |

## 9. Reinicio de pasarela y recuperación

```bash
# 9.1 Parar la pasarela
docker compose stop gateway
```

**Esperado:** en ≤90 s, `curl -s $BASE/system/health | jq .status` pasa a
`"degraded"` y `gw-01` aparece con `stale: true` (sin latido). Los datos
históricos siguen disponibles (la tabla de nodos no se vacía; los nodos pasarán
a `offline` a los 15 min sin eventos).

```bash
# 9.2 Rearrancar
docker compose start gateway
```

**Esperado:** en ≤30 s `system/health` vuelve a `"ok"`, `gw-01` `connected` y
`stale: false`; el flujo de eventos se reanuda (visible en UI y §7). El contador
de `nodes` sigue siendo 12 (los upserts no duplican).

```bash
# 9.3 Reinicio del backend (resiliencia del consumidor)
docker compose restart backend
```

**Esperado:** el backend rearranca, re-aplica migraciones (no-op) y vuelve a
suscribirse al bus; la UI se recupera sola. Los eventos emitidos durante el
reinicio del backend se pierden (pub/sub es fire-and-forget por diseño, ADR 0003)
— el siguiente heartbeat y telemetría reconstruyen el estado.

## 10. Exportación de logs para depuración

```bash
mkdir -p /tmp/noc-debug
docker compose logs --no-color --timestamps backend  > /tmp/noc-debug/backend.log
docker compose logs --no-color --timestamps gateway  > /tmp/noc-debug/gateway.log
docker compose logs --no-color --timestamps postgres > /tmp/noc-debug/postgres.log
docker compose logs --no-color --timestamps redis    > /tmp/noc-debug/redis.log
docker compose ps > /tmp/noc-debug/ps.txt
curl -s http://localhost:8080/api/v1/system/health  > /tmp/noc-debug/system-health.json
curl -s http://localhost:8080/api/v1/system/version > /tmp/noc-debug/system-version.json
tar -czf noc-debug-$(date +%Y%m%d-%H%M).tar.gz -C /tmp noc-debug
```

Para acotar en el tiempo: `docker compose logs --since 10m backend`.
Para más detalle, en `.env` poner `NOC_LOG_LEVEL=DEBUG` y `docker compose up -d`
(recrea backend y gateway con logs de eventos individuales).

---

## Registro de resultados

| Paso | Resultado (OK/FALLO) | Notas |
|---|---|---|
| 1. Arranque | | |
| 2. Contenedores healthy | | |
| 3. Migraciones | | |
| 4. Simulador emite | | |
| 5. Persistencia | | |
| 6. REST | | |
| 7. WebSocket | | |
| 8. Frontend | | |
| 9. Recuperación | | |
| 10. Logs | | |

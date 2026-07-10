# Meshtastic NOC

Plataforma profesional de administración y monitorización para redes
Meshtastic (Network Operations Center): observa la malla en tiempo real,
gestiona la configuración remota de los nodos y alerta ante anomalías, todo
desde una única interfaz web.

## Funcionalidades principales

- **Monitorización en tiempo real** — tabla y mapa (Leaflet) de nodos con
  estado online/offline, posición, batería, SNR y telemetría, actualizados
  por WebSocket.
- **Dashboard NOC** — resumen agregado de la malla, nodos críticos con motivo,
  estado de pasarelas y feed de actividad en vivo.
- **Motor de alertas** — reglas configurables (batería baja, nodo desconectado,
  SNR degradado, pasarela caída) con severidad, notificaciones (webhook/ntfy) y
  ciclo de vida firing → acknowledged → resolved.
- **Organización de nodos** — favoritos, etiquetas, grupos e ignorados, con
  búsqueda y filtros avanzados.
- **Administración remota** — operaciones sobre nodos vía LoRa (lectura de
  metadata/config, cambios seguros con verificación de lectura, favoritos e
  ignorados remotos), con cola persistente, límite de tasa y reintentos.
- **Editor de configuración** — edición completa de `config`/`module_config`
  por secciones, con validación y aplicación por riesgo.
- **Perfiles de configuración** — plantillas versionadas, comparación por
  diferencias y sincronización masiva hacia varios nodos.
- **Acciones masivas (batches)** — selección de nodos, previsualización
  (dry-run) y ejecución con confirmación, seguimiento de progreso y ETA.
- **Consola de actividad** — histórico filtrable de eventos de operaciones,
  lotes y estado de pasarelas.

## Arquitectura

Cuatro servicios orquestados con Docker Compose (ver `docs/adr/`):

- **gateway** — conexión exclusiva al nodo Meshtastic central (serial/TCP/HTTP o
  simulada); publica eventos normalizados en Redis y consume la cola de comandos.
- **backend** — FastAPI: API REST (`/api/v1/docs`), WebSockets, dominio, persistencia.
- **frontend** — React + TypeScript servido por nginx (punto único de entrada).
- **postgres** + **redis** — persistencia y bus de eventos/colas.

## Arranque rápido

```bash
cp .env.example .env
docker compose up --build
```

- UI: http://localhost:8080
- API docs: http://localhost:8080/api/v1/docs

Por defecto el gateway usa el **transporte simulado** (malla ficticia de 12 nodos),
por lo que no se necesita hardware. Para un nodo real por TCP:

```env
GATEWAY_TRANSPORT=tcp
GATEWAY_TCP_HOST=192.168.1.50
```

(El firmware solo admite un cliente TCP a la vez: cierra la app oficial si
está conectada al mismo nodo. Ver `docs/acceptance/tcp.md`.)

Para serial, además descomenta el bloque `devices:` del servicio `gateway` en
`docker-compose.yml`.

## Desarrollo

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

- Frontend con HMR: http://localhost:5173
- Backend con reload: http://localhost:8000/api/v1/docs

## Documentación

- `docs/architecture.md` — documento de arquitectura base.
- `docs/adr/` — decisiones de arquitectura (ADRs).
- `shared/events/` — contrato de eventos gateway ↔ backend (fuente de verdad).

# Meshtastic NOC

Plataforma de administración y monitorización para redes Meshtastic
(Network Operations Center).

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

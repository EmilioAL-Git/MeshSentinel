# ADR 0006 — Contrato de eventos versionado entre gateway y backend

- Estado: Aceptado (2026-06-12)

## Contexto

El gateway depende de la librería `meshtastic`, cuyo modelo de datos cambia entre
versiones de firmware. El resto del sistema debe estar protegido de esos cambios.

## Decisión

- Todos los mensajes gateway↔backend usan un **sobre (envelope) común** con
  `schema_version`, `event_type`, `gateway_id`, `event_id` y `timestamp`.
- Los esquemas se definen como **JSON Schema** en `shared/events/` y son la única
  fuente de verdad del contrato. Versionado con `schema_version` entero; los cambios
  incompatibles incrementan la versión y el backend soporta N y N-1 durante la
  transición.
- Tipos de evento v1: `gateway.status`, `node.seen`, `position.updated`,
  `telemetry.received`, `message.received`, `packet.raw`.
- Comandos v1 (backend → gateway, vía Redis Streams): `command.send_admin`,
  `command.request_position`, `command.traceroute`.

## Consecuencias

- El 70% del sistema se desarrolla contra una pasarela simulada (ADR 0007) que
  emite exactamente este contrato.
- Un cambio en los protobufs de Meshtastic solo toca `gateway/decoder`.

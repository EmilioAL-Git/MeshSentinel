# Contrato de eventos gateway ↔ backend

Fuente de verdad del contrato entre servicios (ver ADR 0006).

- **Eventos** (gateway → backend): canal Redis pub/sub `noc:events`. Todos usan
  `envelope.schema.json`; el `payload` se valida con el esquema del `event_type`.
- **Comandos** (backend → gateway): Redis Stream `noc:commands:<gateway_id>` con
  consumer group `gateway`. Esquema: `command.schema.json`.

## Versionado

- Cada versión vive en su directorio (`v1/`, `v2/`...).
- Cambios compatibles (campos opcionales nuevos): misma versión.
- Cambios incompatibles: nueva versión; el backend acepta N y N-1 durante la transición.

## Reglas

- El gateway nunca publica estructuras de la librería `meshtastic` sin normalizar.
- Todo evento incluye `gateway_id` (soporte multi-pasarela, ADR 0001).
- `node_id` canónico: formato `!xxxxxxxx` (hex de 8 dígitos en minúsculas).

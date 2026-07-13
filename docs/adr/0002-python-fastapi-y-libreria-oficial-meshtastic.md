# ADR 0002 — Python + FastAPI; librería oficial `meshtastic`

- Estado: Aceptado (2026-06-12)

## Contexto

La librería oficial de referencia para hablar con nodos Meshtastic (serial, TCP, BLE,
protobufs) es la de Python. Reimplementar el protocolo en otro lenguaje es un riesgo
de mantenimiento permanente.

## Decisión

- Backend y gateway en **Python 3.12+**.
- API con **FastAPI**: OpenAPI automático (requisito de API documentada), WebSockets
  nativos, validación con Pydantic, async de serie.
- El gateway usa la librería **`meshtastic`** de PyPI, siempre envuelta en un
  adaptador propio (`gateway/transports`) para aislar el resto del sistema de los
  cambios de protobufs entre versiones de firmware. (Nota: tras ADR 0023 el
  alcance exacto es `gateway/transports/meshtastic_stream.py` + `tcp.py` +
  `usb.py`, todos dentro de `gateway/transports`; la decisión no cambia.)
- Firmware objetivo: la versión estable más reciente durante el desarrollo.
  Región LoRa: EU_868.

## Consecuencias

- Un solo lenguaje en los dos servicios de servidor.
- La versión de `meshtastic` se fija (pin) y se actualiza de forma deliberada.
- Ningún módulo fuera de `gateway/transports` y `gateway/decoder` importa
  `meshtastic`.

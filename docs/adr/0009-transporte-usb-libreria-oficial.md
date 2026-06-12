# ADR 0009 — Transporte USB sobre la librería oficial: puente hilos→asyncio y snapshot NodeDB

- Estado: Aceptado (2026-06-12)

## Contexto

La librería oficial `meshtastic` es síncrona: `SerialInterface` lanza un hilo
lector y publica eventos por PyPubSub. El gateway es asyncio. Además, al conectar,
el dispositivo entrega su **NodeDB** (nodos que ya conoce la malla).

## Decisión

1. **Puente hilo→asyncio**: los callbacks PyPubSub (`meshtastic.receive`,
   `meshtastic.connection.lost`) solo encolan en una `asyncio.Queue` mediante
   `loop.call_soon_threadsafe`; nunca tocan Redis ni el event loop directamente.
   La conexión (bloqueante) se ejecuta con `asyncio.to_thread`. Cola acotada
   (1000): si se llena, se descartan paquetes contabilizándolos (`dropped`) —
   preferible a bloquear el hilo lector de la librería.
2. **Decodificador puro** (`gateway/decoder/meshtastic.py`): funciones
   `dict → (event_type, payload v1)` sin I/O, dispatch por `decoded.portnum`
   (NODEINFO/POSITION/TELEMETRY/TEXT_MESSAGE). Testeado contra los JSON Schema
   del contrato sin hardware. Solo este módulo y `transports/usb.py` conocen la
   librería (refuerza ADR 0002).
3. **Snapshot NodeDB al conectar**: se emite un `node.seen` por entrada → el NOC
   se puebla en segundos. Cambio aditivo al contrato v1: campo opcional
   `last_heard` en `node_seen` con la antigüedad real según el dispositivo
   (el backend lo ignora hoy; lo aprovechará sin romper compatibilidad).
   No se emiten posiciones del snapshot: contaminarían el histórico con datos
   antiguos fechados como actuales.
4. `"usb"` se añade al enum de transportes de `gateway_status` (aditivo, v1).

## Limitaciones asumidas (capacidades reales de Meshtastic)

- Telemetría/batería solo cuando cada nodo la difunde (intervalo configurado en
  el nodo); `battery_level` se recorta a 101 (=alimentación externa).
- Firmware solo disponible para el nodo local; el de nodos remotos queda vacío.
- Timestamps de los nodos no fiables (sin RTC): manda la hora de recepción.
- Los nodos del snapshot aparecen "online" hasta el umbral de 15 min aunque
  lleven tiempo callados (el backend aún no consume `last_heard`).

## Consecuencias

- Backend y frontend no requieren cambios; el USB es indistinguible del simulador.
- Cambios de formato entre versiones de la librería se absorben en el decoder.

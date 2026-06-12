# ADR 0003 — Redis como bus de eventos y cola de trabajos

- Estado: Aceptado (2026-06-12)

## Contexto

Se necesitan tres mecanismos: difusión de eventos en tiempo real (gateway → backend
→ WebSocket), una cola persistente con ACK para comandos admin sobre LoRa (lentos,
con reintentos) y caché de estado de red.

## Decisión

**Redis 7** cubre los tres usos:

- **Pub/Sub** (`noc:events`) para el flujo de eventos en tiempo real.
- **Streams + consumer groups** (`noc:commands:<gateway_id>`) para la cola de
  comandos con entrega fiable, ACK y reintentos.
- Claves estándar para caché.

Se descartan RabbitMQ/Kafka (sobredimensionados para el hardware objetivo) y la
comunicación HTTP directa backend↔gateway (acoplamiento de arranque, pérdida de
eventos en reinicios).

## Consecuencias

- Un contenedor adicional, ligero y multi-arch.
- Los eventos pub/sub son *fire-and-forget*: lo que deba persistir se persiste en
  base de datos por el backend, no se confía en el bus.
- La cola de comandos es por-gateway, lo que habilita multi-pasarela (ADR 0001).

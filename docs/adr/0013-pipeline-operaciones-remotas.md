# ADR 0013 — Pipeline de operaciones remotas (M1.1): cola en BD, presupuesto de malla y ciclo de vida por eventos

- Estado: Aceptado (2026-07-08)
- Contexto de diseño: `docs/design/modulo1-administracion-remota.md` (§4)

## Decisión

1. **La cola es la base de datos** (`admin_operations`): persistente, auditable y
   sobrevive a reinicios. Redis Streams solo transporta el comando al gateway
   (mecanismo ADR 0003). El gateway hace **ACK siempre** tras procesar: los
   reintentos los gobierna el backend (estados + backoff), nunca la re-entrega
   del stream — evita ejecuciones dobles sobre LoRa.
2. **Presupuesto de malla**: rate limit global (`NOC_ADMIN_RATE_LIMIT_PER_MINUTE`,
   default 6) + 1 operación en vuelo por gateway (consumo secuencial del stream).
3. **Ciclo de vida por eventos**: el gateway publica `admin.operation`
   (running/succeeded/failed/timeout — cambio aditivo al contrato v1) y el
   backend aplica la máquina de estados: reintento con backoff exponencial
   (10 s ×2, tope 300 s) hasta `max_attempts`; watchdog que expira operaciones
   colgadas si el gateway muere; resultados tardíos de operaciones
   canceladas/terminales se ignoran.
4. **Solo GET en M1.1**: `metadata.get`, `nodeinfo.get`, `config.get(section)`,
   `module_config.get(section)`. El registro de capacidades
   (`application/admin/registry.py`) es la fuente de verdad (params, allow_bulk,
   destructive, required_role) — añadir una operación = una entrada + su soporte
   en el gateway.
5. **Ejecución en gateway**: peticiones construidas como `AdminMessage`
   (protobuf oficial) de forma uniforme y enviadas con `Node._sendAdmin(want
   Response=True)`; el `getNode(requestChannels=False)` evita tráfico extra.
   Las respuestas ADMIN_APP se correlacionan con *futures* por
   `(node_id, response_key)` desde el flujo de paquetes ya existente. Riesgo
   asumido: `_sendAdmin` es API privada de la librería (los métodos públicos
   equivalentes están orientados a CLI); queda confinado a `decoder/admin.py`
   y `transports/usb.py` (ADR 0009).
6. **El simulador ejecuta admin** (ADR 0007): latencia 0.5–2 s y ~10% de
   timeouts deterministas por seed — el pipeline completo (cola → reintentos →
   historial → UI) se valida sin hardware.

## Consecuencias

- Enrutado por `nodes.gateway_id` (última pasarela que oyó al nodo): base del
  multi-gateway futuro.
- El passkey de sesión admin (PKC) no se gestiona explícitamente en GETs; los
  SET de M1.4 incorporarán `ensureSessionKey` y los estados
  `succeeded_unconfirmed`/`verify_failed`.

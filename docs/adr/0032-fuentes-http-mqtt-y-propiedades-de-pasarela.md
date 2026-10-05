# ADR 0032 — Fuentes HTTP y MQTT, y propiedades de pasarela (solo recepción, primaria, orden, resync)

Estado: aceptada (2026-10-05). Motivación: revisión de MeshMonitor (multi-fuente) y los problemas de
estabilidad con nodos TCP de un único cliente.

## Decisiones

1. **Transporte `http`** (`gateway/transports/http.py`). La librería `meshtastic` 2.7 ya no incluye
   `HTTPInterface`; se implementa `HttpMeshInterface(MeshInterface)` sobre `/api/v1/fromradio` y
   `/api/v1/toradio`. Hereda de `MeshtasticStreamTransport` (ADR 0023: sin forks por transporte), así
   que reconexión, snapshot, telemetría y pipeline admin son los de USB/TCP. Ventaja: el servidor HTTP
   del firmware no está limitado a un cliente. Coste medido: el volcado inicial va una trama por GET
   (`all=true` concatena sin delimitador, no es parseable) → ~40 s con 200 nodos; el timeout de
   sincronización es de 150 s.
2. **Fuente `mqtt`** (`gateway/transports/mqtt.py`), **solo ingesta**. `paho-mqtt` se suscribe a un
   broker, descifra los `ServiceEnvelope` de los canales con PSK conocida (AES-CTR, nonce = id+origen)
   y los pasa por una `MeshInterface` sin dispositivo, de modo que el decoder v1 es el de siempre.
   Nunca transmite (`send_command`/`execute_admin` lanzan `ConnectionError`). Geofiltro opcional
   (`geo_bbox`): un nodo cuya posición cae fuera se ignora (no se purga lo ya guardado — a diferencia
   de MeshMonitor). Solo se parsean temas `…/e/…`; PKI/DM cifrados no se pueden descifrar y se
   cuentan como `undecryptable`.
3. **Solo recepción.** `gateways.receive_only` (decisión del operador) y `gateways.tx_enabled`
   (runtime: el gateway lee `lora.tx_enabled` del nodo local —solo si la config LoRa ya llegó, el
   default proto3 daría un falso "false"— y MQTT reporta siempre `false`). `GatewayInfo.can_transmit`
   = no `receive_only` y `tx_enabled is not False`. El enrutado de operaciones que emiten a la malla
   las excluye (candidatas, fallback, forzado → 409 con motivo; Nexus: scan/operaciones/lote → 409).
   Ingerir sigue funcionando. Contrato v1 aditivo: `gateway.status.tx_enabled`, enum `transport` += `mqtt`.
4. **Primaria designada** (`gateways.is_primary`, única). Pasarela de último recurso del enrutado: se
   usa solo cuando ninguna pasarela con enlace válido ni la caché `nodes.gateway_id` resuelven el
   nodo, y solo si está operativa. Los selectores Nexus la preseleccionan.
5. **Resincronización manual** (`command.gateway_resync`, aditivo): relee el nodo local y
   republica el snapshot de NodeDB sin cortar el enlace, saltándose la ventana anti-flap.
6. **Orden manual** (`gateways.sort_order`; `POST /gateways/reorder`).
7. Migración 0032 (4 columnas). `receive_only`/primaria/orden/resync son solo `admin`.

## Consecuencias / límites asumidos

- Las contraseñas MQTT se guardan en `connection_params` (JSON) y viajan como variable de entorno al
  contenedor, igual que el resto de secretos de la app; se enmascaran sin sesión.
- Una fuente MQTT pública puede traer cientos de nodos ajenos a la BD: usar `geo_bbox`.
- `receive_only` manual es independiente de `tx_enabled`: quitar la marca no fuerza al firmware.

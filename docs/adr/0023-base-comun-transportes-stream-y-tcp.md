# ADR 0023 — Base común de transportes stream y soporte TCP

- Estado: Aceptado (2026-07-10)
- Complementa: ADR 0002 (librería oficial solo en gateway), ADR 0009/0010
  (transporte USB, reconexión), ADR 0019 (ack-only y sus erratas), ADR 0021
  (TransportManager, gestión de gateways)

## Contexto

TCP figuraba como "fase futura" desde Fase 0: aceptado en la config del
gateway (`GATEWAY_TCP_HOST`/`GATEWAY_TCP_PORT`), en el enum del contrato v1,
en el regex de la API de gateways y en `_PARAM_FIELDS` del TransportManager
(M5) — pero sin transporte real detrás (`create_transport` lanzaba
`NotImplementedError`). El usuario dispone de un nodo accesible por TCP y
quiere usarlo para acelerar desarrollo y pruebas del resto del proyecto.

Toda la lógica de valor del transporte USB (puente PyPubSub→asyncio,
reconexión con backoff, snapshot de NodeDB, y el pipeline completo de
administración remota con las 6 erratas de ADR 0019) no depende de que la
interfaz sea serial: `SerialInterface` y `TCPInterface` heredan ambas de
`StreamInterface` en la librería oficial y publican exactamente los mismos
topics PyPubSub. Copiar `usb.py` habría duplicado ~430 líneas de código
endurecido en campo.

## Decisión

1. **Base común `MeshtasticStreamTransport`**
   (`gateway/transports/meshtastic_stream.py`): TODO el comportamiento del
   antiguo `MeshtasticUsbTransport` movido (no copiado) a una clase base.
   Las subclases solo implementan dos hooks:
   - `_connect_blocking()` — cómo se crea la MeshInterface (la ÚNICA
     diferencia real entre transportes);
   - `_endpoint_description()` — cómo describir el endpoint en logs.

   **Prohibido introducir forks de lógica entre transportes**: cualquier
   corrección al pipeline (nuevas erratas de ack-only, session keys, etc.)
   se hace en la base y aplica a todos por construcción. Los mensajes de log
   usan `self.name` como prefijo (`usb.connected`, `tcp.connected`), así que
   los procedimientos operativos existentes que buscan `usb.*` siguen
   funcionando.

2. **`MeshtasticUsbTransport`** queda reducido a: autodetección de puerto
   (`findPorts`), creación de `SerialInterface` y `discover_devices()` para
   el asistente de la UI.

3. **`MeshtasticTcpTransport`** (`gateway/transports/tcp.py`): crea
   `TCPInterface(hostname, portNumber)` (puerto 4403 por defecto, el del
   firmware). Sin autodetección posible: `tcp_host` vacío es un error de
   configuración que no se auto-cura, así que se valida **en el
   constructor** (`ValueError`) — un `test_connection` mal formado falla al
   instante en vez de entrar al bucle de backoff. `connection_params`:
   `{host, port}` (ya mapeados en M5). Limitación operativa documentada: el
   firmware solo admite un cliente TCP simultáneo (la app oficial conectada
   al mismo nodo compite por el socket).

4. **Bug corregido en `TransportManager._start` (M5)**: hacía `teardown()`
   del transporte activo ANTES de construir el nuevo — un
   `command.gateway_connect`/`test_connection` con tipo no soportado o
   params inválidos destruía la conexión USB/simulada en curso y dejaba la
   pasarela sin transporte, con el error solo en logs. Ahora
   `create_transport()` (que valida tipo y params) ocurre primero; si
   lanza, la conexión activa sobrevive intacta. Además `test_connection`
   captura errores de construcción y devuelve `{ok: false, error}` al
   instante (antes: 25 s de timeout de correlación en el backend), y
   `start_from_env` loguea explícitamente un bootstrap fallido (antes el
   fallo quedaba enterrado hasta el shutdown y el proceso corría sin
   transporte en silencio).

5. **Sin cambios de contrato ni migraciones.** El enum de `gateway_status`
   ya incluía `tcp` desde v1; la API ya lo aceptaba; la tabla `gateways` ya
   guarda `connection_params` JSON. Enrutado Multi-Gateway (ADR 0022),
   scheduler, batches y estadísticas son transporte-agnósticos y funcionan
   sin tocar. UI: el asistente gana la opción TCP (host+puerto manual, sin
   paso de búsqueda); `http` sigue siendo fase futura.

## Consecuencias

- TCP tiene exactamente el mismo comportamiento funcional que USB
  (reconexión, snapshot, ACK, admin remota, telemetría, eventos) porque es
  el mismo código; los tests fijan que la única diferencia es la creación
  de la interfaz.
- El coste de mantener un transporte nuevo baja a ~40 líneas; `http`
  (fase futura) podrá evaluar si encaja en la misma base (la interfaz HTTP
  de la librería no es un stream — probablemente no).
- Riesgo aceptado pendiente de validación con hardware: la librería
  detecta cortes TCP silenciosos (WiFi caída sin FIN) peor que una
  desconexión serial; si en la práctica el estado `connected` se queda
  pegado, se evaluará un keepalive — en la base, nunca solo en TCP.

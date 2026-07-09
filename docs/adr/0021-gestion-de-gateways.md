# ADR 0021 — M5: Gestión de gateways desde la aplicación

- Estado: Aceptado (2026-07-09)
- Complementa: ADR 0001 (gateway desacoplado), ADR 0003 (Redis pub/sub +
  streams por-gateway), ADR 0006 (contrato versionado), ADR 0007 (transporte
  simulado), ADR 0009/0010 (transporte USB, reconexión)

## Contexto

Hasta M5, un proceso gateway es 1:1 con un `GATEWAY_ID` y su transporte
(`GATEWAY_TRANSPORT`, `MESHTASTIC_USB_DEVICE`, ...) se fija por variables de
entorno al arrancar. Cambiar de dispositivo USB, o de tipo de transporte,
exige editar `.env` y reiniciar el proceso (o el contenedor). El backend solo
refleja pasivamente el estado (`GatewayModel`/`GatewayInfo`, tabla `gateways`
ya existente) a partir del heartbeat `gateway.status`; no hay gestión (crear,
editar, desactivar) ni descubrimiento de dispositivos.

El objetivo de M5 es mover la configuración del transporte a la aplicación
(BD + UI), sin resolver aún Multi-Gateway simultáneo (fase futura) ni acoplar
el diseño a USB en particular.

## Decisión

1. **No se introduce un concepto nuevo de "agente" con identidad propia.**
   `gateway_id` sigue siendo la identidad estable del proceso (env var
   `GATEWAY_ID`, bootstrap mínimo junto con `GATEWAY_REDIS_URL`) y sigue
   siendo la clave primaria de la fila en `gateways` — exactamente igual que
   hoy. Esto es lo que ya prepara Multi-Gateway sin rediseño (ADR 0001/0003):
   cuando llegue esa fase, cada gateway adicional es sencillamente otro
   proceso con su propio `GATEWAY_ID`, otro stream de comandos y otra fila.
   Separar "agente" de "gateway" habría añadido un espacio de identidades
   nuevo sin necesidad real hoy.

2. **La tabla `gateways` se extiende (no se sustituye)** con columnas de
   configuración gestionable, además de las de estado runtime que ya existía
   (`status`, `transport`, `local_node_id`, `detail`, `updated_at`):
   `name` (obligatorio, el único identificador que ve el usuario en la UI),
   `managed` (bool: false = fila nacida solo de un heartbeat, aún no
   configurada desde la app — comportamiento de hoy), `transport_type` y
   `connection_params` (JSON: parámetros deseados, p. ej. `{"device": "..."}`
   para USB), `enabled`, `priority` (reservado para autoselección en
   Multi-Gateway, sin lógica todavía), `desired_status`
   (`connected`/`disconnected`, lo que el usuario ha pedido), `deleted_at`
   (borrado lógico), `last_connected_at`/`last_disconnected_at`/`last_error`/
   `last_error_at` (historial mínimo, no una tabla de eventos), y una caché
   *no durable* del nodo local (`local_short_name`, `local_long_name`,
   `local_hw_model`, `local_firmware_version`) que se sobrescribe en cada
   conexión — no hace falta historizarla (pedido explícito del usuario).

3. **El transporte pasa a ser dirigible en caliente mediante comandos**, no
   solo configurable al arrancar. `gateway/transport_manager.py` (nuevo)
   sustituye la creación estática de `create_transport()` en `main.py`: crea,
   sustituye y destruye instancias de `Transport` en respuesta a comandos
   recibidos por el stream de comandos ya existente (`noc:commands:<gateway_id>`,
   ADR 0003), reutilizando la interfaz `Transport` sin tocarla. Nuevos tipos
   de comando (aditivos a `command.schema.json`):
   - `command.gateway_discover` — escanea dispositivos USB locales
     (`MeshtasticUsbTransport.discover_devices()`, nuevo, basado en
     `meshtastic.util.findPorts()` + `serial.tools.list_ports` para
     descripción/VID/PID/serial) y responde con el evento
     `gateway.devices_found`.
   - `command.gateway_test_connection` — igual que `connect` pero con
     `wait_timeout`: el `TransportManager` espera el primer `gateway.status`
     con `connected` o `error` de la conexión en curso (correlacionado por un
     contador de generación interno, para no confundir con una conexión
     anterior) y responde con `gateway.test_connection_result`. Si falla, se
     desmonta; si tiene éxito, la conexión queda activa (no se cierra y se
     vuelve a abrir en el guardado posterior: una única reconexión de más al
     guardar es aceptable a cambio de no duplicar la lógica de conexión).
   - `command.gateway_connect` — sustituye la instancia de `Transport` activa
     por una nueva con `transport_type`/`connection_params` dados (o
     reconecta con los mismos si ya estaba desconectado). Cubre tanto "cambiar
     de dispositivo" como "reconectar": no hace falta un comando `assign`
     independiente.
   - `command.gateway_disconnect` — cierra la conexión activa y no reintenta
     hasta el próximo `command.gateway_connect` (se sale del bucle de
     reconexión con backoff propio de cada `Transport`).
   El arranque del proceso **no cambia**: sigue auto-conectando con los env
   vars igual que hoy (compatibilidad total, cero regresión); los comandos
   solo entran en juego después, para redirigir esa conexión sin reiniciar.

4. **Contrato de eventos v1, cambios aditivos:**
   `gateway_status.schema.json` gana los estados `unassigned` (sin conexión
   activa tras un `disconnect`) y `reconnecting` (distinto de `connecting`:
   se emite cuando la conexión ya estuvo `connected` alguna vez y el
   transporte está reintentando tras una caída — permite a la UI pintar
   🟢/🟡/🔴 con matices en vez de un cambio brusco, pedido explícito del
   usuario) y los cuatro campos `local_*` opcionales. Nuevos schemas
   `gateway_devices_found.schema.json` y
   `gateway_test_connection_result.schema.json`.

5. **Reconciliación mínima, sin loop nuevo.** Si el proceso se reinicia (p.
   ej. tras un despliegue) volvería a arrancar con la configuración de
   `.env`, perdiendo la que el usuario fijó desde la app. En vez de un nuevo
   bucle en background, `IngestService._on_gateway_status` (ingest.py)
   detecta el caso reutilizando el umbral de stale ya existente
   (`gateway_stale_after_seconds`, ADR de Fase 1): si la fila anterior estaba
   *stale* (proceso ausente) y la nueva fila es `managed` con
   `desired_status="connected"`, se reenvía `command.gateway_connect` con los
   `connection_params` persistidos. Es un efecto secundario acotado dentro de
   una ruta ya existente, no infraestructura nueva.

6. **Borrado lógico.** "Eliminar gateway" marca `enabled=false,
   deleted_at=now()`; nunca se borra la fila (preserva la referencia de
   `admin_operations.gateway_id`, `node.gateway_id`, etc.). Los listados
   excluyen `deleted_at IS NOT NULL` por defecto, mismo patrón que
   `include_ignored` de M1.2.

7. **Compatibilidad `.env`.** Una fila con `managed=false` (heartbeat sin
   configuración de aplicación, comportamiento de hoy) se sigue mostrando en
   `GET /gateways` con un aviso "importar"; `POST /gateways/{id}/import` crea
   la configuración (`managed=true`) tomando el `transport`/`detail` del
   último heartbeat como valor inicial (best-effort: para USB no se conoce el
   `device` exacto si fue autodetectado, se deja vacío = autodetección,
   editable después). A partir de ahí toda gestión pasa por la API/UI.

## Consecuencias

- Cero tabla nueva; una sola migración que amplía `gateways`.
- `Transport`/`create_transport()` no cambian de interfaz; el acoplamiento a
  USB sigue confinado a `gateway/transports/usb.py` y
  `gateway/decoder/meshtastic.py` (ADR 0002 intacto).
- Multi-Gateway (fase futura) no requiere tocar el modelo de datos: basta con
  levantar más procesos con distinto `GATEWAY_ID`; `priority` ya está
  reservado para la autoselección de un gateway principal.
- Limitación conocida y aceptada: si el proceso se reinicia y el backend no
  ha detectado aún el hueco de heartbeat (ventana de hasta
  `gateway_stale_after_seconds`), reconectará brevemente con la config de
  `.env` antes de que la reconciliación lo corrija en el siguiente heartbeat
  gestionado.

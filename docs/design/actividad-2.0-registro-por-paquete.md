# Actividad 2.0 — Revisión: un paquete decodificado = una entrada

> Estado: **IMPLEMENTADO** (2026-07-12, pendiente de validación del
> usuario). Ver §8 al final del documento para el resumen de lo construido
> y las verificaciones realizadas. Tercera revisión
> de la filosofía de Actividad, pedida por el usuario tras validar la
> Fase 1 implementada (`actividad-2.0-fase1-eventos-legibles.md`, ya en
> el código): Actividad deja de ser el diario de *hechos* y pasa a ser el
> **registro cronológico exhaustivo de paquetes decodificados**. Los
> hechos importantes ya tienen su sitio (Alertas, Centro); Actividad
> responde a "¿qué paquetes circulan ahora mismo por la red?".
>
> **Cuarta revisión (este documento)**: corrige el vocabulario de
> cabecera — nada de nombres internos del protocolo
> (`POSITION_APP`/`NODEINFO_APP`/...) en la vista principal, siempre en
> lenguaje natural de operador. Se añade una capa técnica expandible
> ("Ver paquete") que conserva RSSI/SNR/tipo interno/JSON normalizado sin
> ensuciar la cabecera. Sustituye la decisión §5.3 de la revisión
> anterior (idioma del `packet_type`) y añade el modelo de dos capas
> (humana + técnica) al resto del diseño, que se mantiene igual.

## 1. Auditoría de la implementación actual (Fase 1, en el código hoy)

Infraestructura — **toda reutilizable sin tocar**:

- `ActivityEvent` (`application/activity_events.py`): modelo renderizado
  completo (source/severity/icon/title/node_label/description/details/
  gateway_id/batch_id/timestamp) que viaja como `activity.event` por
  `ActivityPublisher.emit_activity` → `hub.broadcast` → frontend.
- Frontend: `activity.ts` solo traduce `activity.event`; `ActivityConsole`
  pinta icono + título + detalles. React no conoce Meshtastic. Esto ya es
  exactamente lo que pide esta revisión — no cambia.
- Narrativas `gateway` (transiciones), `alert` (listener del motor) y
  `admin` (operaciones/lotes): **no son paquetes** y no cambian — el
  Registro las sigue mostrando entre los paquetes, como hasta ahora.

Lo que SÍ contradice la nueva filosofía (todo dentro de la fuente `mesh`,
en `IngestService` + sus renderers):

| Comportamiento actual (hechos) | Problema bajo la nueva filosofía |
|---|---|
| **Telemetría unificada**: cualquier `telemetry.received` genera UNA tarjeta con `latest_by_kind` (estado del nodo, mezcla device+environment+power) | Fusiona paquetes. Debe ser: paquete device → entrada DEVICE TELEMETRY con SOLO sus campos; environment → ENVIRONMENT TELEMETRY aparte; power → POWER TELEMETRY aparte |
| **Reinicio detectado** SUSTITUYE a la entrada de telemetría | Oculta el paquete. La entrada del paquete debe aparecer SIEMPRE; el reinicio es un hecho, no un paquete (ver §5, decisión pendiente) |
| **NodeInfo solo se narra si hay novedad** (nodo nuevo o cambio de identidad) | Un NODEINFO_APP periódico sin cambios es un paquete real circulando y debe verse como entrada NODE INFO, siempre |
| `position.updated` y `message.received` | Ya son 1 paquete = 1 entrada — solo cambia la presentación (tipo de paquete visible, campos del paquete) |

Métodos afectados en `ingest.py`: `_narrate_node_seen` (línea ~140),
`_on_telemetry` (~235) y sus renderers `render_telemetry`/`render_reboot`/
`render_new_node`/`render_identity_changed` en `activity_events.py`.
`latest_by_kind` (repositorio) deja de usarse por el renderer de
telemetría (se conserva: es lectura genérica útil).

## 2. Qué partes de `ActivityEvent` deben modificarse

Dos capas por entrada, ambas construidas por el backend — el frontend
solo pinta, nunca interpreta ni traduce:

**Capa humana** (vista principal, siempre lenguaje natural):
- `packet_type: str | None` — la cabecera, ahora en **español, redactada
  como los ejemplos del usuario**: "Telemetría del dispositivo",
  "Telemetría ambiental", "Posición actualizada", "Mensaje recibido",
  "Información del nodo", "Información de vecinos", "Traceroute",
  "Waypoint compartido". Nunca el nombre del portnum. `None` para
  gateway/alert/admin (que conservan su título de frase completa tal
  cual, sin cambios).
- `node_label`, `description`, `details` — sin cambios de tipo, solo de
  contenido (campos por-paquete en vez de estado unificado, §1).
- `icon`, `severity` — sin cambios.

**Capa técnica** (oculta tras "Ver paquete", expandible, nunca en la
cabecera): nuevos campos aditivos —
- `rssi: int | None`, `snr: float | None` — ya viajan en varios payloads
  de dominio pero hoy no llegan al `ActivityEvent`; se añaden como
  campos propios (no como `details`, para que el frontend los pinte en
  una sección aparte y no se cuelen en la vista humana).
- `internal_type: str | None` — el nombre técnico real
  (`POSITION_APP`, `NODEINFO_APP`...), solo visible dentro del
  desplegable.
- `raw: dict[str, Any] | None` — el payload de dominio normalizado tal
  cual llegó a `IngestService` (`p` en cada `_on_*`), ya JSON-serializable
  (son dicts del contrato v1) — es el "JSON normalizado expandible" que
  pide el usuario; no hace falta guardar el paquete crudo de la librería
  (eso sigue siendo terreno exclusivo del gateway, ADR 0009).

`gateway_id` ya existe en el modelo y se sigue mostrando en la vista
principal (como hoy, chip de pasarela) — es "gateway receptor", no
técnico en el sentido que preocupa al usuario.

Cambio de semántica documentado en el propio módulo: `ActivityEvent`
representa "una entrada del registro", con una presentación humana
obligatoria y una capa técnica opcional siempre disponible al expandir.

## 3. Paquetes soportados por el decoder hoy

`gateway/decoder/meshtastic.py::decode_packet` reconoce exactamente 4 de
los ~29 `portnum` de `portnums_pb2.PortNum`:

| portnum (`internal_type`, solo en "Ver paquete") | evento v1 | cabecera humana (`packet_type`) | campos de la vista principal |
|---|---|---|---|
| `TELEMETRY_APP` (kind device) | `telemetry.received` | 🔋 Telemetría del dispositivo | Batería, Voltaje, Tiempo encendido, Canal utilizado, Air Util TX |
| `TELEMETRY_APP` (kind environment) | `telemetry.received` | 🌡 Telemetría ambiental | Temperatura, Humedad, Presión |
| `TELEMETRY_APP` (kind power) | `telemetry.received` | ⚡ Telemetría de energía | Voltaje |
| `POSITION_APP` | `position.updated` | 📍 Posición actualizada | Latitud, Longitud, Altitud, Satélites, Precisión* |
| `TEXT_MESSAGE_APP` | `message.received` | 💬 Mensaje recibido | texto entre comillas, canal/destinatario |
| `NODEINFO_APP` | `node.seen` | 👤 Información del nodo | Nombre (long_name), Alias (short_name), Rol |

\* `precision_bits` ya viaja en el contrato y se persiste, pero el
renderer actual no lo muestra — se añade convertido a metros aproximados
(o el valor crudo si la conversión resulta confusa; a decidir en
implementación).

## 4. Paquetes que faltan por soportar

Ampliación del decoder (contrato v1 aditivo, mismo patrón que los 4
existentes — el gateway solo normaliza, cero narrativa):

| portnum (`internal_type`) | evento v1 nuevo | cabecera humana (`packet_type`) | datos disponibles en el dict de la librería |
|---|---|---|---|
| `NEIGHBORINFO_APP` | `neighbors.seen` | 🛰 Información de vecinos — "N vecinos detectados" + lista `EA2DEF -8 dB` | `decoded.neighborinfo.neighbors[{nodeId, snr}]` (los node_num necesitan resolverse a `!xxxxxxxx` en el decoder y a nombres en el backend) |
| `TRACEROUTE_APP` | `traceroute.completed` | 🧭 Traceroute — ruta `EA2ABC → EA2XYZ → EA2DEF` | `decoded.traceroute.{route, snrTowards, routeBack, snrBack}`; solo se emite si `route` no está vacío |
| `WAYPOINT_APP` | `waypoint.shared` | 📌 Waypoint compartido — nombre ("Refugio Sur") + lat/lon | `decoded.waypoint.{name, description, latitudeI, longitudeI, icon}` |

La ingesta de estos 3 es **solo narrativa** en esta fase (sin tabla nueva:
la persistencia de topología `node_neighbors` sigue siendo el diseño
aparte de `motor-de-reglas-y-topologia.md` §2, no bloquea ni se bloquea).

**Deliberadamente fuera** (igual que en las revisiones anteriores):
`ROUTING_APP` (ACK/NAK: transporte puro — pertenece a la consola técnica
de paquetes crudos, `actividad-2.0-consola-de-eventos.md` fases 2+),
`ADMIN_APP` (interceptado por el pipeline M1.1; sus hechos ya se narran
como fuente `admin`), y los módulos de laboratorio (`AUDIO_APP`,
`ATAK_*`, `IP_TUNNEL_APP`, `SERIAL_APP`, `ZPS_APP`, `PAXCOUNTER_APP`,
`STORE_FORWARD_APP`, `RANGE_TEST_APP`, `DETECTION_SENSOR_APP`,
`MAP_REPORT_APP`, `REMOTE_HARDWARE_APP`, `POWERSTRESS_APP`,
`PRIVATE_APP`, `REPLY_APP`, `TEXT_MESSAGE_COMPRESSED_APP`, `ALERT_APP`):
sin tráfico real que mostrar hoy, se añadirían uno a uno cuando exista.

## 5. La capa técnica expandible ("Ver paquete")

Frontend: cada entrada del Registro gana un control plegable (cerrado por
defecto — "vista principal completamente humana", como pide el usuario).
Al expandir, se muestra: `internal_type` (portnum real), `rssi`/`snr` si
existen, `gateway_id` (ya visible arriba, se repite aquí por completitud
técnica) y `raw` formateado como JSON (mismo estilo de bloque que ya usa
el proyecto en otros sitios de solo-lectura, sin sintaxis coloreada
nueva). Cero interpretación en React: es JSON crudo ya serializado por el
backend, tal cual — ninguna librería ni parser adicional.

Esto es, deliberadamente, un adelanto pequeño y acotado de la "consola de
paquetes" de `actividad-2.0-consola-de-eventos.md` (fases 2+): no la
sustituye (esa fase sigue trayendo virtualización, filtros de solo
errores/duplicados, timeline con pausa, etc.), pero cubre ya la necesidad
puntual de "quiero poder mirar el dato crudo de esta entrada concreta"
sin esperar a esa fase.

## 6. Cómo adaptar sin romper Alertas, Trabajos ni el resto

- **Alertas**: cero contacto. El motor, sus reglas, el listener narrador
  (`node_offline`/`low_battery`/`snr_degraded`) y `alert.fired/resolved`
  no se tocan — sus entradas siguen apareciendo en el Registro como
  fuente `alert`, entre los paquetes.
- **Trabajos/opTracker**: cero contacto. `admin.operation`/`admin.batch`
  técnicos intactos; la narrativa admin (`created`/`retry`/`finished`)
  tampoco cambia — son sucesos del pipeline, no paquetes, y el usuario
  pidió no eliminar la infraestructura.
- **Persistencia**: sin cambios — `_on_telemetry`/`_on_position`/
  `_on_node_seen` siguen persistiendo exactamente igual; solo cambia el
  bloque de narración final de cada método.
- **Frontend**: añadido visual acotado (cabecera humana + control
  plegable "Ver paquete"); filtros, categorías, buffer y paneles
  (`ActivityPanel` del Centro incluido) siguen funcionando porque
  `ActivityEntry` solo gana campos opcionales (`packetType`, `rssi`,
  `snr`, `internalType`, `raw`).
- **Snapshots de NodeDB** (`node.seen` con `last_heard`): se mantienen
  EXCLUIDOS del registro. No son paquetes circulando ahora — son la caché
  histórica del dispositivo volcada al conectar; narrarlos contradiría la
  pregunta que Actividad debe responder y produciría una avalancha de
  entradas falsas en cada reconexión de pasarela.
- **Volumen**: una entrada por paquete multiplica el ritmo del feed
  respecto a los "hechos" (sobre todo NodeInfo periódicos). El buffer de
  500 y el flush de 1 s existentes lo absorben; la virtualización queda
  para la fase de consola técnica como estaba previsto.

### Decisiones pendientes de confirmación (bloquean solo su punto)

1. **Reinicio detectado**: bajo la nueva filosofía es un *hecho*, no un
   paquete. Propuesta: la entrada DEVICE TELEMETRY aparece SIEMPRE, y el
   reinicio se emite como entrada ADICIONAL (crítica, como hoy) — dos
   entradas para ese paquete. Alternativa purista: mover el reinicio al
   motor de alertas como regla nueva y sacarlo de Actividad. Recomendada
   la primera (barata, no pierde la señal; la regla puede llegar después).
2. **Nodo nuevo / cambio de identidad**: mismo caso — propuesta: la
   entrada "Información del nodo" aparece siempre, y "ha aparecido por
   primera vez"/"ahora se identifica como" se emiten como entrada
   adicional cuando ocurren (hoy ya existen y funcionan).

(La decisión de idioma de la cabecera de la revisión anterior queda
resuelta por este documento: español natural, nunca el nombre del
portnum — §2/§3/§4 arriba.)

## 7. Plan de migración (fases pequeñas, cada una con el sistema en verde)

1. **Modelo + presentación** (sin cambiar aún qué se narra):
   `ActivityEvent.packet_type/rssi/snr/internal_type/raw` (todo aditivo)
   + cabecera humana y control "Ver paquete" en `ActivityConsole` +
   campos equivalentes opcionales en `ActivityEntry`. Los eventos
   existentes los llevan a `None` — cero cambio visible todavía.
2. **Mesh por-paquete**: reescribir los renderers de telemetría (uno por
   kind, solo campos del paquete), NodeInfo (siempre, con Nombre/Alias/
   Rol), posición (añadir precisión) y mensaje (presentación "Mensaje
   recibido"), todos rellenando ya `rssi`/`snr`/`internal_type`/`raw`.
   Retirar la tarjeta unificada (`latest_by_kind` deja de usarse en
   narración). Reinicio e identidad según decisiones §6.1/§6.2. Ajustar
   los tests de `test_activity_events.py` a la nueva semántica.
3. **Decoder**: `NEIGHBORINFO_APP`/`TRACEROUTE_APP`/`WAYPOINT_APP` →
   esquemas v1 aditivos (`neighbors_seen`/`traceroute_completed`/
   `waypoint_shared`), casos nuevos en `IngestService` (touch_last_seen +
   narración, sin tabla), renderers "Información de vecinos"/
   "Traceroute"/"Waypoint compartido" con resolución de nombres vía el
   labeler existente. Tests de decoder (gateway) y de narración (backend).
4. **Verificación**: suite completa + ruff + tsc/build + stack aislado
   (patrón `act20`) comprobando por WS que N paquetes → N entradas, que
   la cabecera nunca muestra nombres de portnum, que "Ver paquete"
   expone rssi/snr/internal_type/raw correctamente, y que Alertas/
   Trabajos siguen intactos; captura Playwright del Registro con una
   entrada expandida.

Sin migraciones de BD, sin dependencias nuevas, sin cambios en APIs REST.

## 8. Estado de implementación (añadido al implementar)

Las 4 fases se implementaron en un único pase (el usuario no pidió
detenerse entre ellas). Contrato v1: `telemetry_received`/
`position_updated`/`message_received` ganaron `rssi`/`snr` (y
`channel_index` telemetría) aditivos; 3 esquemas nuevos
(`neighbors_seen`/`traceroute_completed`/`waypoint_shared`) + 3 entradas
nuevas en el enum de `envelope.schema.json`. Decoder
(`gateway/decoder/meshtastic.py`): `NEIGHBORINFO_APP`/`TRACEROUTE_APP`/
`WAYPOINT_APP` añadidos (traceroute solo emite con `route` resuelto);
radio metadata (rssi/snr) añadida a telemetría y posición, que antes no
la llevaban. `ActivityEvent` ganó `packet_type`/`internal_type`/`rssi`/
`snr`/`raw`. Un renderer por tipo de paquete
(`application/activity_events.py`): telemetría con 3 funciones
independientes (`render_device_telemetry`/`_environment_`/`_power_`,
despachadas por `render_telemetry_packet(kind, ...)` — nunca fusionan
campos entre kinds), `render_node_info` (siempre), `render_position`
(+precisión aproximada desde `precision_bits`), `render_message`,
`render_neighbor_info`, `render_traceroute`, `render_waypoint`. Los
hechos adicionales (`render_reboot`, `render_new_node`,
`render_identity_changed`) se conservan tal cual pero ahora se emiten
**junto a** la entrada del paquete, nunca en su lugar — confirmado por
`_narrate_node_seen`/`_on_telemetry` en `ingest.py` y sus tests
(`test_ingest_node_info_always_plus_new_node_fact`,
`test_ingest_reboot_is_additional_entry_not_a_replacement`). Frontend:
`ActivityEntry` ganó `nodeLabel`/`packetType`/`internalType`/`rssi`/
`snr`/`raw`; `ActivityConsole` muestra el nombre del nodo bajo la
cabecera y un control plegable "▸ Ver paquete" (estado local por
`event_id`) con la capa técnica en monoespaciado, incluido el JSON crudo
del payload de dominio.

**Bug encontrado y corregido durante la verificación**: `precision_bits`
en máxima precisión (32, el valor que envía el simulador) producía un
radio de incertidumbre bien por debajo de 1 metro; formatear con
`{:.0f} m` lo redondeaba a "0 m", engañoso para un operador (sugiere
incertidumbre nula). Corregido: por debajo de 1 m se muestra "< 1 m".

**Verificación**: 285 tests backend+gateway (24 nuevos en
`test_activity_events.py`, 8 nuevos de decoder), ruff y `tsc -b`/`npm run
build` limpios. E2E en un stack Docker aislado (`act20`, sin tocar el
stack dev del usuario): tráfico real del simulador (telemetría/posición)
capturado por WebSocket crudo y visualmente con Playwright, más eventos
sintéticos publicados directamente en Redis (mensaje, NodeInfo,
NeighborInfo, Traceroute, Waypoint) para cubrir los tipos que el
simulador no genera — capturas confirman cabeceras 100% en español sin
nombres de portnum, telemetrías de distintos nodos como entradas
independientes nunca fusionadas, y el desplegable "Ver paquete" mostrando
`internal_type`/RSSI/SNR/JSON correctamente.

# Diseño: Actividad 2.0 — la consola de eventos de MeshSentinel

> Estado: **DISEÑO, sin implementar**. Pedido explícito del usuario, con el
> mismo nivel de análisis previo que el sistema de Grupos y que
> `docs/design/motor-de-reglas-y-topologia.md`. No se escribe código hasta
> aprobación explícita, fase por fase (mismo procedimiento que el resto de
> MeshSentinel desde M1.2).

## 0. Filosofía (reformulación del encargo)

Hoy "Actividad" es una traducción legible de eventos de dominio ya
persistidos (nodos, alertas, operaciones, lotes, pasarelas). Es correcta
para lo que cubre, pero **no es una consola de NOC**: no muestra tráfico de
malla a nivel de paquete, no conserva conversación, no transmite ritmo salvo
por el pulso decorativo del panel lateral, y pierde en silencio casi todo lo
que la radio realmente recibe. Actividad 2.0 no sustituye lo que ya
funciona (M1.1–M6.2, ADR 0017): lo **envuelve** con una capa nueva de traza
de paquetes y conversación, con la misma filosofía "recomponer, no
reescribir" del principio 10 de `v0.7-centro-de-operaciones.md`.

Objetivo de producto: que mirar la pantalla 5 segundos sin leer una sola
línea ya diga "la malla está viva, aquí, así de rápido, con estos actores".

## 1. Auditoría del estado actual

### 1.1 Contrato de eventos (`shared/events/v1`)

- `envelope.schema.json` ya reserva un `event_type` **sin implementar ni
  usar en ningún sitio**: `"packet.raw"`. Es decir: alguien (Fase 0) ya
  anticipó que haría falta un evento de paquete crudo, pero nunca se
  definió su payload ni se emitió jamás. **Esto es un cimiento gratis**:
  reutilizar ese nombre en vez de inventar uno nuevo.
- Eventos con esquema definido hoy: `gateway.status`, `node.seen`,
  `position.updated`, `telemetry.received`, `message.received`,
  `admin.operation`, `gateway.devices_found`,
  `gateway.test_connection_result`. Todos son **resúmenes de dominio**, no
  trazas de transporte: ninguno lleva `hop_limit`/`hop_start` crudos,
  tamaño de paquete, `channel` (existe en `message.received` únicamente),
  `rssi` (falta en `message.received`, solo tiene `snr`), id de paquete
  para detectar duplicados, ni ningún campo de "resultado" (ok/duplicado/
  descartado/error de decodificación).
- `admin.batch` y los estados aditivos de `admin.operation`
  (`created/dispatched/running/retry_scheduled/resend_scheduled/finished`)
  no viven en `shared/events/` sino que se generan backend-side en
  `application/activity.py` — son eventos de **actividad**, un vocabulario
  paralelo al contrato gateway↔backend, ya con precedente de convivir en el
  mismo canal WS (ver §1.4).

### 1.2 Decoder del gateway (`gateway/decoder/meshtastic.py`, `decode_packet`)

Es el punto de mayor pérdida de información hoy. `decode_packet` solo
reconoce 4 `portnum`: `NODEINFO_APP`, `POSITION_APP`, `TELEMETRY_APP`,
`TEXT_MESSAGE_APP`. Cualquier otro paquete —`ROUTING_APP` (ACK/NAK de
tráfico normal, no de administración), `NEIGHBORINFO_APP`,
`TRACEROUTE_APP`, `WAYPOINT_APP`, `STORE_FORWARD_APP`, `MAP_REPORT_APP`,
paquetes cifrados sin `decoded` (canales privados con PSK propia), o
cualquier `portnum` desconocido— devuelve `None` y en
`transports/meshtastic_stream.py:_pump_events` (línea 192) el paquete se
descarta con solo un contador en memoria (`self._counters["ignored"] += 1`)
que **nunca sale del proceso** salvo un log INFO cada 100 eventos
(`_log_counters`, línea 205). Ni siquiera queda rastro de que ese paquete
existió.

Los `ADMIN_APP` (administración remota) sí se interceptan, pero en
`_resolve_admin_response` (línea 226), *antes* de llegar a `decode_packet`,
y solo para resolver los `Future` en espera del pipeline M1.1/M1.3/M1.4/
M4.1/M4.2 — tampoco dejan traza de "se recibió un ADMIN_APP de tipo X" en
la consola, aunque el propio decoder ya conoce ese contenido perfectamente
(`gateway/decoder/admin.py`).

Los 4 tipos que sí se decodifican **tampoco preservan** varios campos que
el usuario pide explícitamente: `hopStart`/`hopLimit` crudos (solo se
deriva `hops_away`), tamaño del paquete, `channel` (salvo en mensajes de
texto), ni un identificador de paquete para detectar retransmisiones o
duplicados vistos por más de una pasarela (relevante con Multi-Gateway,
M6.2).

### 1.3 Persistencia (`application/ingest.py`)

`IngestService.handle_event` solo tiene casos para `node.seen`,
`position.updated`, `telemetry.received`, `gateway.status`; `message.received`
únicamente actualiza `last_seen_at` (línea 78-81) y **no persiste el
mensaje en ningún sitio** — no existe tabla de mensajes. Cualquier
`event_type` no reconocido cae al `case _` y se descarta con un log debug
(línea 82-83). Esto significa que hoy, si nadie tiene el navegador abierto
en el momento exacto en que llega un mensaje de chat, **ese mensaje se
pierde para siempre**, sin ninguna forma de recuperarlo.

### 1.4 Bus y WebSocket (`main.py`, `adapters/api/ws.py`)

El diseño ya es, sin saberlo, el correcto para lo que se propone aquí:
`app.state.event_bus.subscribe(hub.broadcast)` (main.py:63) reenvía **todo**
evento del bus Redis a todos los clientes WS conectados, tal cual, sin
filtrar por `event_type`. Es decir: **el día que el gateway empiece a
emitir `packet.raw`, ya llega al frontend sin tocar `ws.py` ni `main.py`**.
`activity.attach(hub.broadcast)` (línea 66) hace lo mismo para los eventos
de actividad backend-side. El único filtro de "qué me interesa" vive hoy en
el frontend (`DATA_EVENTS`, `App.tsx:46`).

Limitación real: `ConnectionHub` (`ws.py`) no tiene ningún backlog. Un
cliente que se conecta tarde, o que sufre un corte de red, no recibe lo que
pasó mientras estuvo desconectado — la app hoy lo resuelve invalidando
todas las queries HTTP al reconectar (App.tsx:246-253), pero eso solo sirve
para estado agregado (nodos, alertas...), **no existe ningún mecanismo
para "recuperar los últimos N minutos de eventos crudos"**, que es
exactamente lo que pide el punto 4 (Timeline) del encargo.

### 1.5 Frontend: `activity.ts` + `ActivityConsole.tsx` + `ActivityPanel.tsx`

- `App.tsx:46-55` (`DATA_EVENTS`) decide qué `event_type` se procesan.
  **Bug/hueco encontrado durante esta auditoría**: `message.received` NO
  está en `DATA_EVENTS`, pese a que `activity.ts:225-230`
  (`describe()` → `case "message.received"`) ya sabe convertirlo en una
  entrada de actividad. Resultado: **los mensajes de chat que el backend
  reenvía hoy nunca llegan a ninguna pantalla** — ni la pestaña Actividad
  ni el panel lateral los muestran, aunque el evento viaja por el WS. Es un
  hueco real, no solo una carencia de diseño.
- El buffer (`App.tsx:176,194-237`) es un `Array<ActivityEntry>` de 500
  entradas máximo, con `unshift`/`slice` cada segundo (batching de 1 Hz) y
  deduplicación de heartbeats consecutivos idénticos. Sin virtualización:
  `ActivityConsole.tsx:156` (`filtered.map(...)`) renderiza un `<div>` por
  entrada visible. Con 500 líneas de texto es tolerable; con "miles de
  eventos" de tráfico de paquete, no.
- No hay ninguna dependencia de virtualización en `frontend/package.json`
  hoy (comprobado).
- Categorías actuales (`activity.ts:6`): `operacion | batch | pasarela |
  alerta | malla` — todo lo que no es operación/lote/pasarela/alerta cae en
  "malla" sin distinguir `node.seen` de `telemetry.received` de
  `message.received`. Insuficiente para los filtros pedidos ("solo
  telemetría", "solo administración", "solo usuario").
- El panel `Consola` (eventos crudos, JSON plegado) está **diseñado en
  `v0.7-centro-de-operaciones.md` §6.6 pero nunca implementado** —
  `OpsCenter.tsx` solo registra los paneles `activity`/`jobs`/`alerts` en
  `ConsoleRail`. Es la pieza más cercana en espíritu a "consola de
  paquetes", pendiente desde v0.7.1.
- Ya existen y son reutilizables sin cambios: conexión a Inspector
  (`onOpenNode`), Focus (`toggleFocus`/`focusId`), centrar en mapa
  (`locateNode` en `App.tsx`, ya enchufado a `ActivityPanel`), y el patrón
  de "pausar autoscroll + botón ↓ N nuevas" que el propio diseño v0.7 ya
  describe para el panel Actividad (aunque tampoco está implementado, solo
  documentado).

### 1.6 NeighborInfo (Fase D)

**Ya existe un diseño completo, aprobado como documento, sin implementar**:
`docs/design/motor-de-reglas-y-topologia.md` §2. Define evento aditivo
`neighbors.seen`, tabla append-only `node_neighbors`, decoder
`decode_neighborinfo`, repositorio y endpoint `GET /nodes/{id}/neighbors`.
Actividad 2.0 **no reinventa esto**: lo consume tal cual cuando exista, y
solo añade lo que le es propio (cómo se muestra en la consola como línea de
evento y cómo se detecta un cambio respecto al estado anterior — ver §5.8).

## 2. Qué información ya recibimos (pero no se ve)

- Todo paquete que atraviesa `meshtastic.receive` en el gateway, incluido
  RSSI/SNR/hopStart/hopLimit/canal/`viaMqtt`, para los 4 tipos decodificados
  — estos datos **existen en el dict de la librería en cada paquete**, el
  decoder simplemente no los traduce todos al payload v1.
- Todo paquete `ADMIN_APP` de respuesta (M1.1 y sucesivos) — se procesa
  pero no se traza como evento observable.
- El propio ritmo del pipeline: contadores `total/ignored/decode_errors/
  dropped/admin_responses/stale_disconnects` por transporte
  (`_counters`, `meshtastic_stream.py:44`) — hoy solo en logs.

## 3. Qué información se pierde hoy

1. **Todo paquete no perteneciente a los 4 tipos decodificados**: ACK/NAK de
   tráfico normal (`ROUTING_APP`), NeighborInfo, Traceroute, Waypoint,
   Store&Forward, MapReport, cualquier `portnum` futuro, y paquetes cifrados
   sin `decoded` — se cuentan y se tiran.
2. **Duplicados/retransmisiones**: no hay noción de "paquete visto dos
   veces" (mismo id, misma o distinta pasarela) en ningún punto del
   pipeline.
3. **Mensajes de chat**: no se persisten (confirmado, §1.3) y ni siquiera
   llegan a la UI hoy (bug de `DATA_EVENTS`, §1.5). No hay historial
   recuperable tras un refresco de página.
4. **Nombres de canal**: el sistema conoce `channel_index` (solo en
   mensajes) pero no el nombre humano del canal (LongFast/LongSlow/
   Primary/Emergency...) — esa información vive en la configuración de
   canales del dispositivo local de cada pasarela (`iface.localNode.
   channels`), nunca leída ni expuesta.
5. **Backlog de eventos crudos**: sin persistencia efímera, un cliente que
   abre la pestaña Actividad tarde, o se reconecta, no puede "retroceder
   unos minutos" — solo ve lo que llega desde ese instante.
6. **Salud del propio decoder**: los contadores de paquetes descartados/
   con error de decodificación existen en memoria del gateway pero no se
   exponen — un operador no puede saber "esta pasarela está recibiendo
   ruido que no sabemos interpretar" sin mirar logs del contenedor.

## 4. Qué habría que conservar (principio de retención)

Tres naturalezas de dato con retención deliberadamente distinta — no todo
merece vivir en PostgreSQL para siempre (violaría el principio de dominio
"observador pasivo" y el de diseño 9, "la ausencia de problema no ocupa
espacio", si además ensuciáramos la base de datos con ruido de transporte):

| Naturaleza | Ejemplo | Retención propuesta |
|---|---|---|
| **Señal de dominio** (ya cubierta) | node.seen, position, telemetry | Tal cual hoy: tablas append-only permanentes. Sin cambios. |
| **Traza de transporte** (nueva) | paquete crudo, ACK/NAK, duplicado, descartado | **Efímera**: buffer en memoria (backend), suficiente para "los últimos N minutos"/"hidratar al abrir la pestaña". Nunca en PostgreSQL. |
| **Conversación** (nueva) | mensajes de texto (chat) | **Persistente de verdad**: es contenido humano deliberado, no telemetría de fondo — pérdida = pérdida real para el operador. Tabla nueva, sin purga automática (o purga muy larga, a decidir). |

Esta distinción es la decisión de arquitectura central del documento — es
la única forma de dar "miles de eventos por hora" sin migrar el proyecto a
una base de datos de series temporales de alto volumen, cosa que nadie ha
pedido y que contradice el principio de "el gateway es observador pasivo,
LoRa es de ancho de banda mínimo" (el volumen real de paquetes por hora en
una malla EU_868 es bajo comparado con lo que "miles de eventos" sugiere en
otros dominios — el diseño debe soportarlo con holgura, no asumir que hará
falta).

## 5. Arquitectura propuesta

### 5.1 Nuevo evento v1: activar `packet.raw`

Se define por fin el payload del `event_type` ya reservado en el envelope.
Aditivo puro: ningún esquema existente cambia.

```jsonc
// shared/events/v1/packet_raw.schema.json
{
  "from_node_id": "!xxxxxxxx",        // o null si no se pudo resolver
  "to_node_id": "!xxxxxxxx | null",   // null = broadcast
  "packet_id": 123456,                 // id crudo de la librería (dedupe)
  "portnum": "ROUTING_APP",           // o "UNKNOWN_042" / "ENCRYPTED"
  "channel_index": 0,
  "hop_start": 3,
  "hop_limit": 1,
  "size_bytes": 27,
  "snr": 7.5,
  "rssi": -98,
  "via_mqtt": false,
  "want_ack": false,
  "status": "ok",                     // ok | duplicate | encrypted | decode_error | unknown_portnum
  "summary": "ACK (routing, errorReason=NONE)"  // texto corto específico del tipo, ver abajo
}
```

- **Decoder** (`gateway/decoder/meshtastic.py`): nueva función pura
  `decode_packet_trace(packet, seen_ids) -> dict`, que **se ejecuta
  siempre**, para todo paquete, en paralelo a `decode_packet` (no lo
  sustituye — los 4 tipos existentes se siguen emitiendo como hoy,
  además). Nunca devuelve `None`: si no reconoce el `portnum` igualmente
  produce una línea de traza con `status="unknown_portnum"`.
  - `size_bytes`: `packet.get("raw")` es el `MeshPacket` protobuf original
    de la librería; `.ByteSize()` da el tamaño real sin reinventar nada.
  - `status="encrypted"`: cuando `decoded` no es un dict (canal con PSK
    que este gateway no conoce) — hoy esto se descarta en silencio.
  - `status="duplicate"`: comparar `packet_id` contra una ventana corta de
    ids vistos (`collections.OrderedDict` o `set` acotado, TTL ~60 s,
    *dentro del propio transporte* — un duplicado visto por dos pasarelas
    *distintas* no se puede deduplicar en el gateway, solo backend/frontend
    podrían correlacionarlo cruzando `packet_id` entre `gateway_id`s; se
    deja como posible mejora de fase 2, no bloquea fase 1).
  - `summary`: texto corto específico por `portnum` conocido (p.ej. para
    `ROUTING_APP`: `"ACK"`/`"NAK (errorReason)"`; para `ADMIN_APP`:
    `"admin: get_config"` reutilizando lo que `gateway/decoder/admin.py`
    ya sabe interpretar) — sin esto la consola solo diría "ROUTING_APP",
    poco útil para un operador.
- **`_pump_events`** (`meshtastic_stream.py:169`): tras el `if
  self._resolve_admin_response(packet): continue` y el `decode_packet`
  existente, se añade una llamada **incondicional** a
  `decode_packet_trace` y se publica como `packet.raw` — sin excepciones
  que puedan tumbar el pump (mismo `try/except` defensivo que ya protege
  `decode_packet`).
- **Contadores de pipeline** (§3.6): se añaden al payload de
  `gateway.status` (aditivo) en el próximo heartbeat: `packets_total`,
  `packets_ignored`, `decode_errors`, `dropped` — reutiliza
  `self._counters` que ya existe, solo lo expone.

### 5.2 Retención de la traza: buffer en memoria, no SQL

Nueva pieza en el backend: `application/activity_buffer.py` (nombre a
discutir), un `deque(maxlen=N)` (p.ej. 3000) por proceso, alimentado por el
mismo `IngestService.handle_event` con un `case "packet.raw"` que **no
persiste en BD**, solo empuja al deque compartido. Endpoint nuevo:

```
GET /api/v1/activity/recent?event_type=&node_id=&limit=500
```

Sirve dos propósitos: (a) hidratar la consola al abrir la pestaña o
recuperar el WS tras un corte (§1.4), y (b) es la base técnica del
"timeline"/buffer circular pedido en el punto 4 del encargo — pausar el
scroll en el frontend ya no pierde nada mientras el deque backend siga
teniendo esos eventos.

Alternativa descartada: tabla SQL `packet_trace` con purga por cron. Se
descarta explícitamente por ahora: multiplica el volumen de escritura de la
base de datos por cada paquete de la malla (contradice la retención
`append-only` deliberadamente reservada solo a señal de dominio, §4) para
un beneficio (persistencia entre reinicios del backend) que nadie ha
pedido. Si en producción real se echa en falta, es una fase 2 acotada
(mismo patrón `node_positions`/`node_telemetry`, con purga por edad).

### 5.3 Chat: persistencia real

Nueva tabla append-only (Alembic, migración aditiva, mismo estilo que
`node_positions`):

```
messages(id, from_node_id, to_node_id, channel_index, text,
         gateway_id, snr, rssi, received_at)
```

- **Contrato**: `message_received.schema.json` gana `rssi` (aditivo,
  como `snr` ya opcional) — falta hoy y el encargo lo pide explícitamente
  por mensaje.
- **Ingesta**: `IngestService._on_message` nuevo (paralelo a
  `_on_telemetry`), además de `touch_last_seen` que ya hace hoy.
- **Dominio**: `Message` (`domain/nodes/entities.py`, dataclass
  `slots=True`, mismo estilo que `Telemetry`).
- **Repositorio**: `SqlMessageRepository` con `add()` y
  `list_recent(channel_index=None, before=None, limit=100)`.
- **API**: `GET /api/v1/messages?channel_index=&before=&limit=` (historial,
  paginación hacia atrás por `received_at`) + el mismo `message.received`
  ya viaja en vivo por WS (arreglando el bug de `DATA_EVENTS`, §1.5).
- **Frontend fix inmediato, de bajo riesgo**, independiente del resto de
  este documento: añadir `"message.received"` a `DATA_EVENTS`
  (`App.tsx:46`) — hoy el chat literalmente no se muestra en ningún sitio
  pese a que el backend ya lo reenvía. Se puede corregir antes o
  independientemente de las fases de abajo si el usuario lo prefiere.

**Decisión pendiente de aprobación explícita** (arquitectura de producto,
no solo de datos): ¿el chat de MeshSentinel es **solo observador** (lee la
malla, nunca escribe — coherente con "el NOC es observador pasivo",
CLAUDE.md) o el operador debe poder **enviar** mensajes de texto desde la
consola? El encargo original solo describe lectura (autor/hora/gw/rssi/
snr/texto) y no menciona envío, pero "chat global" sugiere ambigüedad. Se
recomienda **fase 1 solo lectura** (consistente con el resto del sistema:
toda escritura hoy pasa por el pipeline auditado de administración remota,
M1.1–M1.4, con cola/rate-limit/confirmación — enviar un `TEXT_MESSAGE_APP`
libre desde la consola sería la primera escritura de "contenido arbitrario"
del sistema, sin ese andamiaje) y evaluar envío como fase posterior si el
usuario lo pide.

### 5.4 Nombres de canal

Nuevo evento informativo aditivo `gateway.channels` (o extender
`gateway.status` con un campo opcional `channels`, a decidir en
implementación): al conectar (`_on_connected`, `meshtastic_stream.py:117`),
leer `self._iface.localNode.channels` (lista de `Channel` proto con
`index`, `settings.name`, `role`) y emitirlo. Se persiste como columna JSON
nueva `gateways.channels` (mismo patrón de extensión de tabla que M5,
`connection_params`), refrescada en cada conexión. El frontend arma el
selector de canales fusionando los `channels` de todas las pasarelas
conectadas (clave = `channel_index`; primer nombre no vacío gana; si ningún
gateway tiene nombre para ese índice, fallback `"Canal {index}"`).
Limitación aceptada: si ninguna pasarela conectada conoce un canal (p.ej.
antes de la primera conexión, o pasarela sin ese canal configurado), el
selector no puede ofrecerlo hasta que alguna lo reporte — coherente con
"observador pasivo", nunca se fuerza una lectura de configuración no
solicitada por el propio ciclo de conexión.

### 5.5 NeighborInfo (Fase D del encargo)

Se reutiliza íntegro el diseño ya aprobado en
`motor-de-reglas-y-topologia.md` §2 (evento `neighbors.seen`, tabla
`node_neighbors`, decoder, repositorio, endpoint). Lo único propio de
Actividad 2.0:

- Cada `neighbors.seen` recibido se traduce también en 0..N líneas de
  consola: comparando el snapshot recién insertado contra el
  `list_latest_for_node` anterior (mismo query que ya propone ese diseño
  para "lo último") se puede derivar "enlace nuevo con NODE-4 (SNR 6.2)",
  "enlace perdido con NODE-7" o "cambio de calidad NODE-4: SNR 3.1→6.2".
  Este diffing es responsabilidad de `IngestService` en el mismo paso que
  persiste (no del frontend: los datos "antes/después" solo están
  disponibles ahí antes de que la fila vieja se pierda entre lecturas),
  publicado como evento de actividad `neighbor.link_changed`
  (backend-side, mismo patrón que `admin.batch`/`admin.operation` en
  `application/activity.py`).
- Nueva categoría en la consola: "vecino" (§5.7).
- No bloquea el resto de Actividad 2.0: si NeighborInfo nunca se
  implementa (o el firmware no lo emite), la consola de paquetes y el chat
  funcionan exactamente igual sin esta pieza.

### 5.6 Vocabulario de estado por línea

Cada línea de la consola de paquetes necesita un "estado" visualmente
distinto (pedido explícito): `ok` (verde/neutro), `duplicate` (gris,
atenuado — "ya visto"), `encrypted` (ámbar tenue — "sin poder leer"),
`decode_error` (rojo), `unknown_portnum` (gris, con el nombre crudo del
portnum visible para poder pedir soporte de ese tipo en el futuro).

### 5.7 Componentes frontend nuevos

- **`components/activity/PacketConsole.tsx`**: la tabla de paquetes, **sin
  HTML `<table>`** (pedido explícito) — filas `.termlog`/`.line`
  reutilizando exactamente las clases de `console.css` que ya usa
  `ActivityConsole.tsx`, con columnas alineadas por `grid-template-columns`
  monoespaciado en vez de `<td>`s. Virtualizada (ver §5.8).
- **`components/activity/ChatPanel.tsx`**: selector de canal (chips o
  `<select>`, según cuántos canales distintos existan — reutiliza el
  patrón `.seg` ya usado para categorías), lista de mensajes con
  hora/autor/gw/RSSI/SNR/texto, hidratada por `GET /messages` +
  actualización en vivo por WS. Vive en la **misma pantalla** que
  PacketConsole (pedido explícito "no un chat separado") — layout de dos
  columnas o pestañas internas dentro de la vista Actividad, a decidir en
  el mockup de implementación (ver §7, pregunta abierta).
- **`activityFilters.ts`**: generalización de `activity.ts` — categorías
  ampliadas (`operacion | batch | pasarela | alerta | malla | trafico |
  chat | vecino`), filtro de texto libre (nuevo, no existe hoy), atajos
  "solo errores"/"solo administración"/"solo usuario"/"solo telemetría"
  como combinaciones predefinidas de categoría+estado, no un concepto
  nuevo.
- **Buffer circular real**: sustituir el array + `unshift`/`slice`
  (`App.tsx:232-236`) por una estructura de anillo (índice de escritura
  módulo capacidad) para el stream de paquetes — a diferencia del buffer
  de actividad actual (500 entradas, throughput bajo), con tráfico de
  paquete el coste de recopiar el array entero cada flush deja de ser
  trivial. Reutilizable también para el buffer de actividad existente si
  se decide unificar.
- **Pausa/reanudación** ("seguir leyendo, luego volver al directo"): mismo
  patrón que el propio diseño v0.7 §6.3 ya dibuja para el panel Actividad
  (botón `[⏸]`, chip `"↓ N nuevas"`) pero nunca implementado — se
  construye aquí por primera vez y el panel Actividad puede adoptarlo
  después sin duplicar trabajo.
- **Integración con Inspector/Focus/mapa**: cada línea reutiliza las
  callbacks ya enchufadas en `ActivityPanel`/`App.tsx`
  (`onOpenNode`→Inspector, `toggleFocus`, `locateNode`→mapa `flyTo`) —
  nada nuevo que construir ahí. "Copiar node_id"/"copiar paquete" son
  triviales (`navigator.clipboard.writeText`), sin dependencias nuevas.

### 5.8 Rendimiento

- **Virtualización**: no hay librería instalada hoy. Se propone
  `@tanstack/react-virtual` (ya se usa `@tanstack/react-query`, mismo
  autor/ecosistema, sin conflicto de versiones esperado) — solo renderiza
  las filas visibles del `<div>` con `overflow: auto`, coherente con el
  resto del proyecto (nada de `<table>`, se pidió explícitamente).
- **Buffer circular** (§5.7) en vez de array + slice: inserción/lectura
  `O(1)` amortizado en vez de recopiar el array completo en cada flush.
- **Batching**: mismo patrón ya validado (`App.tsx:229`, flush cada 1 s)
  pero con una cola *separada* para paquetes (mayor frecuencia potencial
  que operaciones/lotes/alertas) — flush cada ~300 ms para que "se sienta
  viva" sin disparar un render de React por paquete individual. Cap duro
  de líneas añadidas por flush (p.ej. 50) con indicador "+N más" si se
  supera, igual que ya hace `PulseLayer` del mapa (v0.7.3, límite 8/lote).
- **Memoización**: cada fila es un componente memoizado por `event_id`
  (igual que los marcadores del mapa desde Fase 2A) — evita re-render de
  filas ya pintadas cuando solo cambian las nuevas.
- **Streaming, no polling**: se mantiene WS como única vía (ya es así);
  `GET /activity/recent` solo se llama una vez al montar/reconectar, nunca
  en bucle.
- **Coste en el propio bus**: emitir `packet.raw` para *todo* paquete
  duplica aproximadamente el volumen de mensajes por el pub/sub de Redis y
  el fan-out del WS respecto a hoy. Dado el principio de dominio "LoRa es
  de ancho de banda mínimo, duty cycle EU_868", el volumen real esperado
  (paquetes/segundo en una malla física) es bajo comparado con lo que
  "miles de eventos" sugiere — el simulador (`GATEWAY_SIM_SEED`,
  `transports/simulated.py`) sí puede generar tráfico más denso y es el
  entorno correcto para validar el peor caso antes de hardware real.

## 6. Resumen — qué se reutiliza y qué no

**Se reutiliza sin tocar**: envelope v1, fan-out `hub.broadcast` (ya
reenvía cualquier `event_type` nuevo sin cambios en `ws.py`/`main.py`),
`ActivityPublisher` (mismo patrón para `neighbor.link_changed`), Inspector/
Focus/mapa (`onOpenNode`/`toggleFocus`/`locateNode` ya existen y están
enchufados), clases CSS `.termlog`/`.line`/`.seg` de `console.css`
(v0.8), diseño ya aprobado de NeighborInfo (`motor-de-reglas-y-
topologia.md`), patrón de migración/repositorio append-only
(`node_positions`/`node_telemetry` como plantilla exacta para `messages`).

**No merece la pena reutilizar tal cual**: `activity.ts` como único punto
de traducción — crece demasiado si absorbe también paquetes crudos y chat;
se separa en un módulo propio (`activityFilters.ts` o similar) que
comparte tipos pero no la misma función `describe()` monolítica. El buffer
array-based (`App.tsx:194-237`) tampoco escala al volumen de paquete — se
sustituye por un buffer circular, dedicado al nuevo stream.

**Nuevo, no existe nada parecido**: decoder de traza genérica
(`decode_packet_trace`), buffer efímero de traza en el backend (deque en
memoria, sin persistencia SQL), tabla `messages`, lectura de canales
locales (`gateway.channels`), virtualización de listas (dependencia nueva).

## 7. Preguntas abiertas para aprobación (antes de planificar fases)

1. **Chat: ¿solo lectura o también envío?** (§5.3). Recomendación: solo
   lectura en esta primera versión.
2. **Duplicados entre pasarelas distintas** (mismo `packet_id` visto por
   `gw-01` y `gw-02`, Multi-Gateway): ¿vale con marcarlos como líneas
   independientes con el mismo `packet_id` visible (el operador lo
   correlaciona a ojo, dato ya presente), o hace falta correlación
   automática desde ya? Recomendación: líneas independientes por ahora
   (más simple, dato ya suficiente), correlación automática como posible
   fase 2 si en el uso real resulta confuso.
3. **Retención del buffer de traza** (§5.2): ¿tamaño de deque aceptable
   (propuesta: 3000 líneas, algunos minutos de tráfico normal) o el
   usuario prefiere un tiempo explícito ("últimos 15 minutos") en vez de
   un conteo fijo de líneas?
4. **Layout de Chat + Consola de paquetes en la misma pantalla** (pedido
   explícito "no un chat separado"): ¿dos columnas simultáneas, o pestañas
   internas dentro de la vista Actividad con el chat siempre accesible en
   un clic? Se resuelve con un mockup concreto en la fase de UI, no
   bloquea las fases de datos/backend.
5. **NeighborInfo (Fase D)**: ¿se implementa dentro de este mismo esfuerzo
   (aunque sea al final, fase 5) o se mantiene como estaba —
   "diseño aprobado, sin fecha", igual que hoy— y Actividad 2.0 solo dejar
   el hueco preparado (categoría "vecino" ya reservada en el vocabulario,
   sin datos reales hasta que se implemente aparte)?

## 8. Plan de implementación (fases pequeñas, aprobables una a una)

Ninguna fase rompe a las anteriores; cada una deja el sistema en estado
funcional completo, con tests/ruff/tsc/build en verde, igual que el resto
del proyecto.

**Fase 1 — Arreglo inmediato (bajo riesgo, independiente del resto)**
Añadir `"message.received"` a `DATA_EVENTS` (`App.tsx`) para que el chat ya
emitido hoy por el backend por fin aparezca en la consola de Actividad
existente, sin tabla nueva ni endpoint nuevo (efímero, como hoy). Se puede
hacer ya mismo si el usuario quiere, sin esperar al resto del diseño.

**Fase 2 — Traza de paquetes (backend + gateway, sin UI todavía)**
`packet_raw.schema.json`, `decode_packet_trace`, emisión incondicional en
`_pump_events`, contadores de pipeline en `gateway.status`, buffer efímero
backend (`deque` + `GET /activity/recent`). Validable con el simulador y
con `redis-cli`/DevTools antes de tocar frontend.

**Fase 3 — Chat persistente**
Migración `messages`, dominio, repositorio, `IngestService._on_message`,
`rssi` aditivo en el contrato, endpoint `GET /messages`. Sin UI de chat
todavía — validable con curl/tests.

**Fase 4 — Consola de paquetes + Chat en UI**
`PacketConsole.tsx`, `ChatPanel.tsx`, virtualización
(`@tanstack/react-virtual`), buffer circular frontend, filtros ampliados
(`activityFilters.ts`), integración Inspector/Focus/mapa, pausa/reanudación.
Esta es la fase de mayor salto visual perceptible.

**Fase 5 — Nombres de canal**
`gateway.channels`, columna `gateways.channels`, selector de canal real en
`ChatPanel` (antes de esta fase, el selector solo puede mostrar índices
numéricos).

**Fase 6 — NeighborInfo** (si se aprueba incluirla aquí, ver pregunta 5)
Implementación del diseño ya existente en `motor-de-reglas-y-topologia.md`
§2, más el diffing de `IngestService` y la categoría "vecino" en la
consola.

No se escribe una sola línea de código de ninguna fase hasta que el usuario
apruebe este documento y, después, cada fase individualmente — mismo
procedimiento que el resto de MeshSentinel.

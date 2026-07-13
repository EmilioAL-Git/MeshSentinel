# Actividad 2.0 — Fase 1: el diario operativo de la red

> **Estado real (actualizado): SUSTITUIDO.** El mecanismo central de este
> documento — telemetría unificada por nodo (una tarjeta por nodo que
> fusiona device/environment/power vía `latest_by_kind`) y NodeInfo narrado
> solo si hay novedad — **ya no es como funciona el sistema**. Al día
> siguiente de esta implementación, `actividad-2.0-registro-por-paquete.md`
> revirtió esa filosofía a petición del usuario: hoy cada paquete decodificado
> genera siempre su propia entrada (telemetría device/environment/power como
> 3 entradas independientes, NodeInfo siempre, no solo ante cambios). Este
> documento se conserva como rastro de decisión; **para el comportamiento
> vigente, ver `actividad-2.0-registro-por-paquete.md`**.
>
> Estado original de este documento (histórico): **IMPLEMENTADO**
> (2026-07-12, pendiente de validación del usuario). Ver §8 para las
> desviaciones respecto al diseño, todas pedidas explícitamente por el
> usuario en el encargo de implementación o descubiertas durante la
> verificación. Segunda revisión del diseño: cambia la filosofía respecto a
> la primera versión (que seguía pensando en términos de "paquete →
> evento"). Redefine y acota la Fase 1 propuesta en
> `actividad-2.0-consola-de-eventos.md` (aquella era más amplia: consola de
> paquetes + chat + timeline; sigue vigente para fases posteriores, sin
> cambios en ese plan).

## 0. Cambio de filosofía

La versión anterior de este documento razonaba "cada paquete Meshtastic se
convierte en un evento". Es la forma equivocada de pensarlo: liga
Actividad al protocolo, y el operador seguiría —aunque con mejor
redacción— viendo la sombra de los paquetes por debajo ("ha llegado un
DeviceMetrics", "ha llegado un EnvironmentMetrics"...).

La reformulación correcta: **Actividad es el diario operativo de la red**.
No registra tráfico, registra **hechos**. Un hecho no tiene por qué
corresponder 1:1 con un paquete —puede ser la fusión de varios paquetes
recientes en un solo estado ("EA2ABC ha enviado telemetría"), o no proceder
de ningún paquete en absoluto (un nodo lleva 20 minutos sin oírse: eso no
es un paquete, es una *ausencia*). Esto tiene tres consecuencias de diseño
que no estaban en la versión anterior:

1. **La telemetría deja de tener un evento por tipo de métrica**: hay un
   único concepto — "el nodo ha enviado telemetría" — construido a partir
   del **estado actual conocido del nodo**, no del paquete concreto que
   disparó la actualización (§1).
2. **`ActivityEvent` deja de significar "un paquete decodificado"** y pasa a
   significar "un hecho ocurrido en la red", con un origen (`source`)
   explícito que hoy cubre paquetes de malla pero que desde el primer día
   está pensado para acoger reglas, sistema, administración y pasarelas
   (§2).
3. **No todos los hechos pesan igual**: se introduce una prioridad visual
   de 4 niveles, independiente del tipo de paquete y dependiente del
   *significado* (§3).

## 1. Auditoría del decoder actual (`gateway/decoder/meshtastic.py`)

(Sin cambios respecto a la primera revisión — se mantiene íntegra porque
sigue siendo la base factual correcta.)

`decode_packet(packet)` reconoce hoy exactamente 4 `portnum` (de los ~29
que define `portnums_pb2.PortNum`): `NODEINFO_APP`, `POSITION_APP`,
`TELEMETRY_APP`, `TEXT_MESSAGE_APP`. Cualquier otro devuelve `None` y se
descarta en `_pump_events` (`meshtastic_stream.py:192`) sin dejar rastro,
salvo un contador en memoria (`_counters["ignored"]`).

`gateway/__init__.py` de la librería oficial (`protocols` dict) confirma
qué clave usa cada `portnum` dentro de `packet["decoded"]` una vez
decodificado por protobuf — necesario para ampliar el decoder:

| portnum | clave en `decoded` | protobuf |
|---|---|---|
| `ROUTING_APP` | `routing` | `mesh_pb2.Routing` (ACK/NAK, `errorReason`) |
| `NEIGHBORINFO_APP` | `neighborinfo` | `mesh_pb2.NeighborInfo` (`neighbors: [{node_id, snr}]`) |
| `TRACEROUTE_APP` | `traceroute` | `mesh_pb2.RouteDiscovery` (`route`, `route_back`, `snr_towards`, `snr_back`) |
| `WAYPOINT_APP` | `waypoint` | `mesh_pb2.Waypoint` (`name`, `description`, lat/lon, `icon`) |
| `ADMIN_APP` | `admin` | ya interceptado antes del decoder (M1.1, pipeline propio) |
| resto (`STORE_FORWARD_APP`, `PAXCOUNTER_APP`, `MAP_REPORT_APP`, `REMOTE_HARDWARE_APP`, `RANGE_TEST_APP`, `DETECTION_SENSOR_APP`, `AUDIO_APP`, `ATAK_*`, `IP_TUNNEL_APP`, `SERIAL_APP`, `ZPS_APP`, `SIMULATOR_APP`, `PRIVATE_APP`, `REPLY_APP`, `POWERSTRESS_APP`, `ALERT_APP`) | variable | módulos de laboratorio o muy específicos, no narrados en esta fase (§5) |

Tipos hoy ignorados en su totalidad: los ~25 `portnum` que no son los 4 ya
soportados. No todos merecen narrarse (ver §5): `ROUTING_APP` (ACK/NAK) es
ruido de transporte puro, y varios módulos son de laboratorio, casi nunca
activos en una malla real.

## 2. Modelo `ActivityEvent`: un hecho, no un paquete

```python
@dataclass(slots=True)
class ActivityEvent:
    source: str              # "mesh" | "alert" | "gateway" | "admin" | "system"
    priority: str             # "info" | "important" | "warning" | "critical" (§3)
    icon: str                 # un solo emoji/glifo
    title: str                # "ha enviado telemetría" — SIEMPRE en lenguaje natural
    node_id: str | None       # para enlazar con Inspector/Focus/mapa
    node_label: str | None    # "EA2ABC" ya resuelto (nombre o node_id); None si el hecho no es de un nodo (p.ej. una pasarela)
    description: str | None   # texto libre opcional (p.ej. el texto de un mensaje, entre comillas)
    details: list[tuple[str, str]]   # [("Batería", "91 %"), ...] en orden, ya formateado
    gateway_id: str | None = None
```

**`source` es la pieza nueva de esta revisión**: declara de dónde viene el
hecho, no para que el frontend se comporte distinto (siempre renderiza
igual, sea cual sea el origen — mismo componente, mismo layout), sino para
que cada productor sepa a qué se refiere y para poder auditar/filtrar por
origen más adelante si hiciera falta. Fuentes previstas, con las que se
implementan **ahora** marcadas:

| `source` | Qué produce hechos | ¿En esta fase? |
|---|---|---|
| `mesh` | paquetes de la malla (telemetría, posición, mensajes, NodeInfo, NeighborInfo, waypoint, traceroute) | **Sí** |
| `alert` | transiciones del motor de alertas ya existente (ADR 0012): nodo desaparecido/reaparecido, batería baja, enlace degradado | **Sí** (reutilizando el motor, cero lógica de detección nueva — §3) |
| `gateway` | conexión/desconexión de una pasarela | **Sí** (reutilizando `gateway.status`, ya emitido hoy) |
| `admin` | operaciones/lotes de administración remota | **Parcial** — se deja preparado el `source`, pero **no se migra** la narrativa existente de `admin.operation`/`admin.batch` en esta fase (ver §5, para no duplicar dos redacciones distintas del mismo hecho mientras se decide el mapeo "qué operación es *importante*") |
| `system` | eventos internos sin nodo ni pasarela concreta (arranque del backend, etc.) | No, sin caso de uso concreto todavía — solo reservado |

Esto dota a `ActivityEvent` de "un modelo, muchos orígenes", que es
exactamente lo pedido en el Cambio 2: hoy conviven `mesh`/`alert`/`gateway`,
mañana pueden sumarse `admin`/`system` sin cambiar el modelo ni el
frontend, solo añadiendo un productor más.

**Transporte**: sigue siendo el mismo mecanismo ya existente y ya probado
—`ActivityPublisher.emit("activity.event", asdict(event), gateway_id=...)`
(`application/activity.py`), adjunta a `hub.broadcast` en `main.py`—, cero
piezas nuevas. `admin.operation`/`admin.batch`/`gateway.status`/
`alert.fired` **siguen coexistiendo sin cambios** en el bus WS (los sigue
usando, por ejemplo, la vista Alertas para el historial y ACK, o el panel
Trabajos): `activity.event` es una capa de narrativa añadida en paralelo,
no una sustitución de esos eventos técnicos.

**Dónde se genera cada uno**:
- `mesh`: dentro de `IngestService`, en el mismo método que ya persiste
  cada evento de dominio (mismo patrón que la revisión anterior, ver §4).
- `alert`: un listener nuevo del `AlertEngine` (mismo patrón que
  `_ws_alert_broadcaster` en `main.py:99`, que ya escucha
  `AlertTransition` para retransmitir `alert.fired`/`alert.resolved`) que
  traduce **solo** las transiciones de ciertos `rule_type` a
  `ActivityEvent` (§3) — no todas: una transición de una regla sin
  redacción de diario definida simplemente no genera `ActivityEvent`
  (pero `alert.fired` se sigue emitiendo igual para la vista Alertas).
- `gateway`: un renderer sobre `gateway.status` (mismo evento que ya
  procesa hoy `describeGateway` en `activity.ts` del frontend) — se añade
  en el backend, en paralelo a la traducción cliente ya existente (no se
  retira la del frontend en esta fase, ver §5).

## 3. Prioridad visual (4 niveles, por significado)

```python
Priority = Literal["info", "important", "warning", "critical"]
```

| Prioridad | Hechos incluidos | `source` | Disponible ya |
|---|---|---|---|
| **INFO** | telemetría, posición, NeighborInfo, waypoint | `mesh` | Sí |
| **IMPORTANTE** | mensaje recibido, cambio de identidad, nodo nuevo | `mesh` | Sí |
| **WARNING** | batería baja, degradación importante de enlace (SNR) | `alert` (`low_battery`, `snr_degraded`, transición `fired`) | Sí — reglas ya existen (ADR 0012) |
| **WARNING** | pérdida de redundancia | `alert` (`low_redundancy`) | **No** — regla diseñada pero no implementada (`motor-de-reglas-y-topologia.md` §1.2); el hecho no puede narrarse hasta que exista |
| **CRÍTICO** | nodo desaparecido / nodo reaparecido | `alert` (`node_offline`, transición `fired`/`resolved`) | Sí — regla ya existe, sin lógica de detección nueva: se reutiliza el motor de alertas tal cual |
| **CRÍTICO** | gateway desconectado | `gateway` (`gateway.status` → `disconnected`/`error`) | Sí |
| **CRÍTICO** | reinicio detectado | `mesh` (comparación de `uptime_seconds`, §4) | Sí |
| **CRÍTICO** | operación fallida importante | `admin` | **Diferido** (§5) — no se implementa en esta fase |

La prioridad es una propiedad de **qué significa** el hecho, no de qué
paquete lo originó — por eso "nodo desaparecido" y "gateway desconectado"
son CRÍTICO pese a no venir de un paquete de malla en absoluto, y por qué
"batería baja" no se decide con un umbral improvisado en el decoder sino
reutilizando exactamente la regla `low_battery` que el motor de alertas ya
evalúa cada 30 s con su propio `threshold`/`duration_seconds`/
`cooldown_seconds` (ADR 0012) — ninguna lógica de umbral se duplica.

**Nodo desaparecido/reaparecido, por qué viene del motor de alertas y no
del decoder**: la ausencia de un nodo no es algo que ningún paquete anuncie
— se deduce de que ha pasado demasiado tiempo sin oírlo, y esa lógica
(umbral, evaluación periódica) ya existe íntegra en `eval_node_offline`
(`application/alerting/evaluators.py`). Construir una segunda detección de
"ausencia" en el decoder de paquetes sería duplicar lo que el motor de
alertas ya hace bien.

**Gateway desconectado, por qué viene de `gateway.status` y no del motor
de alertas**: existe también una regla `gateway_disconnected` en el motor
de alertas, pero esa regla confirma la caída tras un `duration_seconds` de
margen (para no disparar una alerta por un parpadeo). Para el diario
operativo interesa la noticia **en el instante** en que la pasarela
informa de la desconexión (el mismo dato que hoy traduce
`describeGateway` en el frontend) — se narra ahí, sin esperar la
confirmación de la regla. Las dos cosas conviven sin conflicto: una es el
diario ("ha pasado algo, ahora"), la otra es la alerta gestionable con ACK
("sigue sin resolverse").

## 4. Telemetría unificada (Cambio 1 — tercera opción)

Se descarta tanto "un evento por tipo de métrica" como "ventana de
correlación temporal". La solución: **el renderer de telemetría no
describe el paquete que ha llegado, describe el estado del nodo**.

Mecanismo, sin buffers ni temporizadores, reutilizando el propio
`SqlTelemetryRepository` (ya existe, solo gana un método de lectura
nuevo):

1. Llega `telemetry.received` (de cualquier `kind`: `device`,
   `environment` o `power`). `IngestService._on_telemetry` la persiste
   como hoy (sin cambios en ese punto).
2. Justo después, en la misma transacción, se pide al repositorio el
   **último registro conocido de cada `kind` para ese nodo**
   (`SqlTelemetryRepository.latest_by_kind(node_id) -> dict[str,
   Telemetry]` — 3 lecturas indexadas por `(node_id, received_at)`, el
   mismo índice que ya usa `list_for_node`; el `kind` que acaba de llegar
   ya está entre esos 3 porque se acaba de escribir en el paso 1).
3. El renderer construye **una única** `ActivityEvent` ("EA2ABC ha enviado
   telemetría") con `details` = la unión de todos los campos disponibles
   entre los 3 `kind` en ese momento (batería, voltaje, canal utilizado,
   air util tx, tiempo encendido, temperatura, humedad, presión...) — si
   el nodo nunca ha reportado telemetría ambiental, esos campos
   simplemente no aparecen en `details` (no se inventan valores ni se
   dejan huecos en blanco).

No importa qué paquete concreto haya disparado la actualización: el
resultado narrado es siempre "el estado térmico/energético actual de
EA2ABC", reconstruido de la base de datos, no de la memoria del proceso —
consistente incluso si el backend se reinicia entre dos telemetrías del
mismo nodo.

**Reinicio detectado** sigue siendo un hecho aparte (CRÍTICO, no INFO):
antes de construir el estado unificado, se compara el `uptime_seconds`
recién llegado (solo tiene sentido en `kind=device`) contra el que tenía
ese mismo nodo en el registro de `device` inmediatamente anterior (una
lectura adicional, ya trivial con `list_for_node(node_id, limit=1,
kind="device")` **antes** de insertar la fila nueva). Si el nuevo valor es
muy inferior al anterior, se emite "EA2ABC se ha reiniciado" en vez de "ha
enviado telemetría" — el estado unificado de ese mismo instante puede
seguir mostrándose igualmente en sus `details` (tiempo desde arranque muy
bajo ya lo deja claro).

## 5. Catálogo de hechos: qué se narra y con qué lenguaje

Todos los títulos son ya el texto final — nunca aparece `TelemetryDevice`,
`PortNum`, `NeighborInfoMessage` ni ningún nombre interno; eso queda
reservado para el modo avanzado de una fase futura (`actividad-2.0-
consola-de-eventos.md`).

| Hecho | Prioridad | Icono | Título (con nombre real) | `details` |
|---|---|---|---|---|
| Telemetría (unificada) | INFO | 🔋 | "EA2ABC ha enviado telemetría" | Batería, Voltaje, Canal utilizado, Air Util TX, Tiempo encendido, Temperatura, Humedad, Presión — solo los campos con dato conocido |
| Reinicio detectado | CRÍTICO | 🔄 | "EA2ABC se ha reiniciado" | Tiempo desde arranque |
| Posición actualizada | INFO | 📍 | "EA2ABC ha actualizado su posición" | Latitud, Longitud, Altitud, Satélites |
| Mensaje recibido | IMPORTANTE | 💬 | "EA2ABC ha enviado un mensaje" | — (texto entre comillas en `description`; canal en `details` como "Canal {index}" hasta que existan nombres reales) |
| Nodo nuevo | IMPORTANTE | ✨ | "EA2ABC ha aparecido en la red por primera vez" | Modelo, Firmware (si se conocen) |
| Identidad actualizada | IMPORTANTE | 👤 | "EA2ABC ha actualizado su identidad" | Nombre anterior → nuevo |
| NeighborInfo | INFO | 🛰 | "EA2ABC ha compartido sus vecinos" | N vecinos, Mejor enlace (nombre, SNR) |
| Traceroute | INFO | 🧭 | "EA2ABC ha completado un traceroute" | Ruta como `A → B → C` |
| Waypoint | INFO | 📌 | "EA2ABC ha compartido un punto de interés: {nombre}" | Latitud, Longitud |
| Batería baja | WARNING | 🪫 | "EA2ABC tiene batería baja" | Nivel actual |
| Enlace degradado | WARNING | 📶 | "El enlace con EA2ABC se ha degradado" | SNR actual |
| Nodo desaparecido | CRÍTICO | 🔴 | "EA2ABC ha desaparecido de la red" | Última vez visto |
| Nodo reaparecido | CRÍTICO | 🟢 | "EA2ABC ha reaparecido en la red" | Tiempo desaparecido |
| Gateway desconectado | CRÍTICO | 🛰 | "Gateway {nombre} ha perdido la conexión" | Transporte, detalle |
| ACK/NAK sueltos, módulos de laboratorio | — | — | (sin evento, §1) | — |

## 6. Qué es inmediato y qué depende de trabajo futuro

**Implementable ya** (sin tabla nueva, sin dependencias nuevas, reutilizando
repos/motor de alertas/`gateway.status` existentes): todo el catálogo de
§5 salvo lo indicado como diferido abajo.

**Diferido, fuera de esta fase**:
- **Pérdida de redundancia** (WARNING): la regla `low_redundancy` no existe
  todavía (`motor-de-reglas-y-topologia.md` §1.2) — sin regla no hay
  transición que narrar. Se añade sola cuando esa regla se implemente,
  sin tocar `ActivityEvent`.
- **Operación fallida importante** (CRÍTICO, `source="admin"`): se deja
  fuera de esta fase porque decidir qué hace que una operación sea
  "importante" (¿todas las fallidas? ¿solo los SET con
  `requires_confirmation`? ¿solo tras agotar reintentos?) es una decisión
  de producto propia que merece su hueco — y porque `admin.operation` ya
  tiene hoy una redacción razonable en `activity.ts`/`ActivityPanel`; mover
  esa narrativa al nuevo modelo sin decidir antes el criterio de
  "importante" arriesga tener dos redacciones a la vez del mismo hecho.
  Se retoma en una fase posterior corta, específica.
- **Nombres de canal reales** — igual que en la revisión anterior:
  requiere leer `iface.localNode.channels`, diseñado para una fase
  posterior; mientras tanto, "Canal {index}".
- **Traceroute como conversación completa** (ida y vuelta) y **topología
  de malla persistida** (`node_neighbors`) — igual que en la revisión
  anterior, sin cambios.
- **Consola de paquetes cruda / modo técnico / JSON / hex / envío de
  mensajes** — pospuesto explícitamente por el usuario (documento
  `actividad-2.0-consola-de-eventos.md`, fases 2-4).

## 7. Resumen de cambios (para cuando se apruebe este diseño)

- `gateway/decoder/meshtastic.py`: `decode_packet` gana `NEIGHBORINFO_APP`,
  `TRACEROUTE_APP`, `WAYPOINT_APP` → eventos de dominio aditivos
  (`neighbors.seen`, `traceroute.completed`, `waypoint.shared`), igual que
  en la revisión anterior — sin narrativa, solo datos normalizados.
- `application/activity_events.py` (nuevo): `ActivityEvent` (con `source` y
  `priority`) + funciones puras `render_*`, incluida la construcción del
  estado unificado de telemetría (§4) y la lógica de "cuándo no narrar"
  (NodeInfo sin cambios, traceroute sin ruta resuelta, ACK/NAK siempre).
- `adapters/persistence/repositories.py`: `SqlTelemetryRepository` gana
  `latest_by_kind(node_id)`; `SqlTelemetryRepository.list_for_node(...,
  limit=1, kind="device")` ya cubre la comparación de reinicio.
- `application/ingest.py`: cada `_on_*` existente invoca el renderer tras
  persistir; nuevo `_on_message`/`_on_neighbors`/`_on_traceroute`/
  `_on_waypoint`.
- `main.py`: nuevo listener del `AlertEngine` (junto a
  `_ws_alert_broadcaster`) que traduce transiciones de `node_offline`,
  `low_battery`, `snr_degraded` a `ActivityEvent`.
- Nuevo renderer sobre `gateway.status` (mismo dato que `describeGateway`
  del frontend, traducido también en el backend para `source="gateway"`).
- Frontend: `MeshEventCard.tsx` (o sección específica en
  `ActivityConsole.tsx`) renderiza `activity.event` con icono + prioridad +
  título + `description` + `details`; `DATA_EVENTS` (`App.tsx`) gana
  `"activity.event"`. Nada de esto toca `activity.ts` ni las categorías
  existentes (operación/batch/pasarela/alerta siguen igual, en paralelo).
- Sin migraciones, sin tablas nuevas, sin dependencias nuevas.

## 8. Estado de implementación y desviaciones (añadido al implementar)

Implementado en: `application/activity_events.py` (modelo + renderers),
`application/ingest.py` (narrativa mesh/gateway), `application/activity.py`
(`emit_activity`, labeler inyectable, narrativa admin en `operation`/
`batch`), `alerting/engine.py` (`AlertTransition.rule`, aditivo),
`main.py` (labeler + listener narrador de alertas),
`SqlTelemetryRepository.latest_by_kind`, y frontend `activity.ts` +
`ActivityConsole.tsx` + `DATA_EVENTS`. 266 tests, ruff, tsc y build en
verde; verificado end-to-end en stack Docker aislado (proyecto `act20`,
puerto 18000, gateway simulado) con captura del WS y Playwright.

Desviaciones respecto a las secciones anteriores, todas deliberadas:

1. **La narrativa admin SÍ se implementó** (el §2/§6 la difería; el
   usuario la pidió explícitamente en el encargo de implementación), con
   su criterio de prioridades: IMPORTANTE = acción iniciada por el
   operador (`created`, lote lanzado), WARNING = recuperable
   (`retry_scheduled`), INFO = completada correctamente, CRÍTICO = solo
   fracaso definitivo (`finished` con failed/timeout/verify_failed —
   nunca durante un reintento). `dispatched`/`running` no se narran
   (ruido interno). Los eventos técnicos `admin.operation`/`admin.batch`
   siguen emitiéndose sin cambios (Trabajos/opTracker dependen de ellos).
2. **`title` es la frase completa final** ("EA2ABC ha enviado
   telemetría"), no el predicado suelto del modelo del §2 — el frontend
   no compone nada; `node_label` queda solo para enlazar. El campo de
   prioridad se llama `severity` en el payload (nomenclatura del encargo).
3. **El decoder del gateway NO se amplió**: NeighborInfo, Traceroute y
   Waypoint quedaron excluidos expresamente del encargo ("NO IMPLEMENTAR
   … NeighborInfo visual, Traceroute"); añadir sus eventos de contrato
   sin narrador sería código muerto. Se retoman con la fase de la
   consola de paquetes (documento `actividad-2.0-consola-de-eventos.md`).
4. **Primera identificación de un nodo** (descubierto antes por
   telemetría, `short_name` aún NULL): también se narra como cambio de
   identidad — hueco detectado durante la verificación con el simulador
   (el catálogo del §5 solo contemplaba nodo nuevo y renombrado).
5. **El feed del frontend pasa a ser 100 % backend**: `activity.ts` ya
   solo traduce `activity.event`; las traducciones cliente de
   `node.seen`/`telemetry`/`gateway.status`/`alert.*`/`admin.*`
   desaparecieron del feed (sus hechos llegan ya redactados y con
   nombres resueltos del backend). Con ello sobraron el dedupe de
   heartbeats y el resolvedor de nombres client-side. Pérdida asumida:
   las líneas de `dispatched`/`running` que el feed antiguo mostraba.
6. El envelope aporta el `timestamp` canónico del evento; `ActivityEvent`
   lleva además el suyo propio en el payload (redundante pero pedido como
   campo mínimo del modelo).

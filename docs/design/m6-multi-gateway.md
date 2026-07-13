# M6 — Diseño de Multi-Gateway

> **Estado real (actualizado): parcialmente implementado.** El commit
> `a5a6b12` (M6.2, consolidando M6.1+M6.2+M6.4+M6.7+M6.8 de este plan)
> implementó: `node_gateway_links` (§1.3), visibilidad N:M y redundancia en
> dashboard/mapa (§4), simulador con semilla compartida (§9), y el
> endpoint de estadísticas por pasarela (§11, parcial). **Con una
> simplificación deliberada respecto al ranking de §6**: la selección de
> pasarela al encolar una operación es "primer candidato sano, con
> fallback a `nodes.gateway_id`, sin failover" — no el ranking completo por
> prioridad → saltos → SNR → RSSI → recencia que describe §6, que sigue
> siendo un ítem de `docs/roadmap.md`. **No implementado**: rate limit por
> pasarela (§8/M6.5 — sigue global), la regla de alerta
> `node_gateway_link_stale` (§5.2/M6.3), y la agrupación de ETA
> multi-pasarela (§7/M6.6). Ver `docs/status.md` para el detalle.

Estado original de este documento (histórico): **Aprobado** por el usuario,
con un ajuste incorporado (orden de ranking de calidad de enlace en §3/§6).
Pendiente de resolver las preguntas abiertas del §15 antes de arrancar M6.1.
- Contexto previo: valoración pre-M6 en `CLAUDE.md` (cuatro obstáculos), ADR 0001,
  0013, 0016, 0019, 0020, 0021
- Este documento **no** introduce migraciones, endpoints ni código. Es la base
  para dividir M6 en sub-fases una vez aprobado.

---

## 0. Resumen ejecutivo

El sistema ya fue diseñado desde ADR 0001 pensando en Multi-Gateway: `gateway_id`
es clave primaria de todo lo relevante, el stream de comandos ya es
per-pasarela, y el bus de eventos ya distribuye por `gateway_id`. Lo que
falta **no es infraestructura de transporte, es modelo de datos y políticas de
decisión**: hoy un nodo solo puede tener *una* pasarela asociada
(`nodes.gateway_id`, última que escribió), y el resto del sistema (rate limit
de administración remota, ETA de lotes, alertas) asume implícitamente una
única malla.

La decisión central de este diseño es:

> **Un nodo lógico, una tabla nueva N:M (`node_gateway_links`) que registra
> "qué pasarelas oyen a este nodo ahora mismo", y mantener las columnas
> actuales de `nodes` como una vista derivada ("pasarela primaria") para no
> romper nada que ya funciona.**

Todo lo demás (dashboard, mapa, alertas, enrutado de administración remota,
reparto de lotes, límite de tasa, simulador, actividad, estadísticas) se
construye *sobre* esa tabla, o se ajusta a un modelo ya N:M implícito
(eventos, comandos) que solo necesita dejar de asumir "una sola pasarela" en
sitios puntuales.

---

## 1. Modelo de datos

### 1.1 Estado actual (por qué hace falta cambiar algo)

`NodeModel` (`backend/src/noc/adapters/persistence/models.py:52-72`) tiene
`gateway_id`, `snr`, `rssi`, `hops_away` como columnas **de valor único**.
`SqlNodeRepository.upsert_from_sighting` (`repositories.py:63-74`) sobrescribe
esos campos sin condición en cada `node.seen`, sin comparar con la pasarela
que ya constaba. Es decir: **"el último que escribe gana"**, ya señalado como
pendiente en ADR 0013 y confirmado por la valoración pre-M6.

`touch_last_seen()` (usado por `position.updated`/`telemetry.received`/
`message.received`) es la excepción: **no** toca `gateway_id` en updates, solo
en el insert inicial. Esto explica un comportamiento ya correcto "por
accidente": si la pasarela A deja de oír a un nodo pero la B sigue recibiendo
telemetría/posición, `last_seen_at` sigue avanzando (bien) aunque `gateway_id`
se quede desactualizado o cambie de forma no determinista según qué evento
tipo `node.seen` llegue primero (mal, para todo lo que sí depende de saber
"por dónde" se oye al nodo).

### 1.2 Alternativas consideradas

1. **Duplicar el nodo por pasarela** (una fila de "nodo" por cada
   `(node_id, gateway_id)`). Descartado explícitamente por el usuario: rompe
   la idea de nodo lógico único, obliga a fusionar en cada lectura, y
   contamina claves foráneas (`admin_operations.target_node_id`,
   `node_positions`, etc. tendrían que decidir "cuál" nodo referenciar).
2. **Convertir `nodes.gateway_id` en una columna JSON/array de pasarelas**.
   Descartado: no soporta bien índices, no permite un `last_heard_at` por
   pasarela, y mezcla responsabilidad de identidad (nodo) con la de
   observación (quién lo oye), dificultando cualquier consulta en SQL puro
   (violaría "prohibido SQL dialectal", ya que arrays JSON se consultan de
   forma muy distinta en PostgreSQL y SQLite).
3. **Tabla N:M "estado actual por pasarela" (elegida)**: una fila por par
   `(node_id, gateway_id)` con el último valor observado por esa pasarela.
   Es exactamente el patrón relacional estándar para "nodo visto por varias
   fuentes", compatible con PG y SQLite, y additiva (no toca `nodes`).

### 1.3 Diseño elegido: `node_gateway_links`

Tabla nueva, **estado actual** (no serie temporal — eso ya existe en
`node_positions`/`node_telemetry`, que además ya llevan su propio
`gateway_id` por fila desde siempre, ver §2):

| columna          | tipo      | notas                                            |
|------------------|-----------|---------------------------------------------------|
| `node_id`        | PK compuesta, FK `nodes.id` | |
| `gateway_id`     | PK compuesta, FK `gateways.id` | |
| `rssi`           | int, nullable | último valor visto por ESTA pasarela |
| `snr`            | float, nullable | ídem |
| `hops_away`      | int, nullable | ídem (mismo significado que hoy en `nodes.hops_away`) |
| `via_mqtt`       | bool | ídem |
| `first_heard_at` | datetime | primera vez que esta pasarela oyó a este nodo |
| `last_heard_at`  | datetime, indexado | para calcular "enlace stale" |

Upsert por `(node_id, gateway_id)` en cada `node.seen` — mismo evento que hoy
alimenta `upsert_from_sighting`, sin cambios en el contrato (el payload ya
trae `gateway_id` en el envelope y `rssi`/`snr`/`hops_away` en el payload).

**`nodes.gateway_id`/`snr`/`rssi`/`hops_away` se mantienen** como caché
derivada ("pasarela primaria"), recalculada en el mismo upsert con **la misma
función de ranking de calidad de enlace del §6** (saltos → SNR → RSSI →
recencia; sin el criterio de prioridad manual, que no aplica aquí porque no
hay una operación concreta que enrutar, ver §3). Esto es deliberado: todo el
código que hoy lee `node.gateway_id` (enrutado de administración remota
heredado, alertas, exportaciones, tests) sigue funcionando sin tocarlo. El
código nuevo que quiera ver "todas las pasarelas" consulta
`node_gateway_links`.

**Enlace "stale"**: un `(node_id, gateway_id)` se considera activo si
`last_heard_at` está dentro de `NOC_NODE_OFFLINE_AFTER_SECONDS` (el mismo
umbral que ya define online/offline, reutilizado — no se inventa un segundo
umbral). Filas con enlace stale no se eliminan (auditoría/histórico de "quién
llegó a oír a este nodo"), solo se excluyen de los candidatos activos.

**No se propone** una serie temporal append-only de RSSI/SNR por-recepción en
esta fase (cada paquete generaría una fila, con impacto en volumen no
justificado por ningún requisito planteado). Si en el futuro se pide una
gráfica de evolución de señal por pasarela, es una fase aparte
(`node_gateway_samples`, mencionada como extensión futura en el plan, §14).

---

## 2. Observaciones (RSSI, SNR, última escucha, hops)

Ya resuelto por el diseño del §1.3: `node_gateway_links` es exactamente esa
tabla. Confirmación de que no hay pérdida de información respecto a lo que
ya existe:

- `node_positions` y `node_telemetry` **ya** llevan `gateway_id` por fila
  (son inserts, no upserts) — la posición/telemetría por pasarela **ya**
  está resuelta correctamente hoy, no requiere cambios.
- Lo que faltaba era el "estado de recepción del propio nodo" (RSSI/SNR/hops
  del último `NODEINFO`/`node.seen`), que hoy vive solo en `nodes` de forma
  monovaluada. `node_gateway_links` cierra ese hueco sin tocar las tablas de
  series temporales.
- No existe hoy ningún campo `hop_limit` en el esquema (solo `hops_away`);
  no se inventa uno nuevo, se reutiliza el mismo campo con el mismo
  significado, ahora por pasarela.

---

## 3. Dashboard: ¿qué pasarela representa a un nodo?

Ninguna respuesta única sirve para todos los consumidores; se proponen dos
niveles:

- **Pasarela primaria (para vistas compactas: tabla de nodos, tarjetas del
  dashboard, badge del mapa)**: la de **mejor calidad de enlace** entre los
  enlaces activos, según el mismo ranking del §6 sin el criterio de
  prioridad manual (saltos ascendente → SNR descendente → RSSI descendente →
  `last_heard_at` más reciente como desempate final). Ajuste incorporado tras
  revisión del usuario: la recencia sola no representa bien la calidad real
  de la conectividad (dos pasarelas pueden haber oído al nodo en la misma
  ventana reciente con calidades muy distintas); el número de saltos y la
  relación señal/ruido son mejores indicadores de "por dónde se administraría
  mejor a este nodo" que "quién lo oyó por última vez". Al reutilizar
  exactamente la función de §6, el dashboard tampoco necesita una política
  propia ni una consulta distinta: sigue leyendo `nodes.gateway_id`, ahora
  recalculado con ese criterio.
- **Todas (para vistas de detalle: panel de nodo, popup de mapa expandido)**:
  lista completa de enlaces activos de `node_gateway_links`, ordenada por el
  mismo ranking, con su RSSI/SNR/hops — información de redundancia que hoy no
  existe y es justo el valor añadido de Multi-Gateway. Se añade un contador
  de redundancia (p. ej. "🛰 2 pasarelas") visible en la vista compacta, que
  al pulsar despliega la lista completa.

---

## 4. Mapa

Un nodo sigue siendo **un único marcador** (sin duplicar). Cambios:

- Popup: añade la lista de pasarelas activas (mismo dato que el panel de
  detalle, §3) en vez de una sola línea "pasarela: gw-01".
- Badge de redundancia en el marcador (número pequeño) cuando hay ≥2
  pasarelas activas, igual que en el dashboard — señal visual rápida de qué
  zonas de la malla tienen cobertura solapada (útil para decidir dónde NO
  hace falta una tercera pasarela).
- **No** se propone dibujar líneas gateway↔nodo en esta fase: requeriría que
  toda pasarela tenga coordenadas conocidas (hoy solo si su nodo local tiene
  posición GPS, no garantizado, p. ej. pasarelas fijas sin GPS) y añade ruido
  visual con clustering ya activo (Fase 2A). Se deja como extensión futura
  opcional si el usuario lo pide tras ver el badge en uso.

---

## 5. Alertas

### 5.1 `node_offline` — comportamiento ya correcto, se formaliza

`eval_node_offline` (`application/alerting/evaluators.py`) ya es agnóstico de
`gateway_id`: mira únicamente `nodes.last_seen_at`, que `touch_last_seen`
actualiza con eventos de **cualquier** pasarela. Es decir: **si la pasarela A
deja de oír a un nodo pero la B sigue oyéndolo, hoy YA NO se dispara
`node_offline`** (correcto), aunque sea sin que el diseño lo hubiera buscado
explícitamente. Se mantiene tal cual — es el comportamiento deseado y no
requiere cambios de lógica, solo un test de regresión explícito que hoy no
existe (evita que una refactorización futura acople sin querer esta regla a
`gateway_id`).

### 5.2 Nueva regla opcional: `node_gateway_link_stale`

Lo que sí falta es señalizar el caso de degradación parcial: "la pasarela A
ya no oye a este nodo, aunque siga online gracias a B" — información
operativa útil (puede indicar un problema de antena/orientación de A, no del
nodo). Se propone una regla nueva, **informativa (severidad INFO por
defecto), desactivada por defecto** para no generar ruido en instalaciones de
una sola pasarela:

- Evalúa cada fila de `node_gateway_links` con enlace activo hace más de
  `duration_seconds` sin refrescarse, **mientras el nodo en conjunto sigue
  online** (si el nodo entero está offline, ya lo cubre `node_offline`, no
  se duplica la alerta).
- `subject_type="node_gateway_link"`, `subject_id=f"{node_id}:{gateway_id}"`,
  `correlation_key` análogo, para no interferir con la reconciliación de
  `node_offline` sobre el mismo nodo.
- No se activa `always_resend` ni tiene severidad CRITICAL: es información de
  cobertura, no una avería de red.

### 5.3 `gateway_disconnected` y `low_battery`/`snr_degraded`

`eval_gateway_disconnected` ya itera todas las filas de `gateways` de forma
independiente — no requiere cambios. `eval_low_battery`/`eval_snr_degraded`
siguen leyendo la columna monovaluada de `nodes` (que ahora refleja la
pasarela primaria, §3); es una decisión deliberada, no un olvido: batería y
degradación de SNR son propiedades del **nodo**, no de una pasarela concreta,
así que seguir leyendo el valor consolidado es correcto y no se complica con
la N:M.

---

## 6. Administración remota: elección de pasarela

Hoy `PlannedOperation.gateway_id` (`application/admin/batches.py:59-67`) se
resuelve una vez, a partir del `nodes.gateway_id` monovaluado
(`batches.py:190-194`). Con `node_gateway_links` hay, en general, varios
candidatos por nodo. Se necesita una función pura de selección, análoga a los
evaluadores de alertas (sin estado, testeable):

**Criterios, en este orden** (razonados uno a uno, respondiendo
explícitamente a "prioridad / latencia / RSSI / ruta"; orden confirmado por
el usuario tras revisión — prioriza calidad de enlace real sobre recencia):

1. **Candidatos válidos**: solo pasarelas con `status="connected"` (no
   stale, ver `gateway_stale_after_seconds`) Y un enlace activo (no stale)
   en `node_gateway_links` para ese nodo. Si no hay ninguno, la operación no
   es enrutable (mismo caso que hoy, cuando `node.gateway_id` es `None`).
2. **`gateways.priority`** (columna ya reservada desde M5, sin lógica hasta
   ahora): mayor prioridad gana. Es el único criterio manual/explícito del
   operador — permite forzar "usa siempre esta pasarela si está disponible"
   sin depender de heurísticas de señal, útil por ejemplo cuando una pasarela
   tiene mejor conectividad a Redis/energía aunque su RSSI hacia el nodo sea
   peor.
3. **`hops_away` ascendente** (proxy de "ruta"/latencia): menos saltos
   significa menos paquetes en el aire por operación (relevante bajo duty
   cycle EU_868) y menor probabilidad de pérdida acumulada — se prioriza
   sobre la calidad de señal puntual porque el número de saltos es una
   propiedad más estable de la topología que la fluctuación de señal.
4. **Mejor SNR descendente**: entre candidatos con misma prioridad y mismo
   número de saltos, el SNR es el indicador de calidad de enlace más fiable
   (relación señal/ruido, menos sensible que el RSSI a variaciones de
   potencia de transmisión entre modelos de hardware).
5. **Mejor RSSI descendente** como desempate fino cuando el SNR es igual o
   muy similar.
6. **`last_heard_at` más reciente** como desempate final, solo si todo lo
   anterior empata (mismo criterio reutilizado por la pasarela primaria del
   dashboard, §3, por coherencia — una única función de ranking para ambos
   usos).

**No se automatiza el fallo a otra pasarela dentro de la misma operación**:
ADR 0013 evita explícitamente la doble ejecución sobre LoRa (el gateway
siempre hace ACK del stream; los reintentos los gobierna el backend, no la
redelivery). Cambiar de pasarela a mitad de reintentos de una MISMA operación
podría, en el peor caso, duplicar un SET no idempotente si el primer intento
sí llegó al nodo pero el ACK se perdió. Por tanto:

- Cada intento de una operación ya creada sigue viajando por la misma
  `gateway_id` con la que se creó (sin cambios respecto a hoy).
- Un **reintento manual explícito del operador** (botón "retry" ya existente
  en Operaciones) sí puede volver a evaluar candidatos — el operador ya está
  tomando una decisión consciente de reintentar, momento natural para
  recalcular si la situación de cobertura cambió.
- Cuando hay ≥2 candidatos válidos al crear la operación/lote, la UI expone
  la pasarela elegida y permite al operador **sobrescribirla manualmente**
  antes de confirmar — reutiliza el campo `target_gateway_id` ya reservado
  en `RemoteFlagPlanItem` (ADR 0020) y extiende el mismo patrón a
  `PlannedOperation`.

---

## 7. Batch Engine: reparto entre pasarelas

No requiere un concepto nuevo de "lote multi-pasarela": el reparto **ya es
por-operación**, no por-lote (`PlannedOperation.gateway_id` es un campo por
elemento, `admin_batches` no tiene columna `gateway_id` — confirmado en el
esquema actual). Con la función de selección del §6, `BatchService.create()`
simplemente resuelve `gateway_id` por nodo contra `node_gateway_links` en vez
de contra `nodes.gateway_id` directo. Un lote que abarque nodos de dos mallas
físicamente independientes ya queda repartido correctamente sin cambios de
modelo — es una propiedad que ya tenía la arquitectura, solo había que dejar
de asumir una única pasarela candidata por nodo.

**Lo que sí cambia es la estimación de ETA** (`estimate_seconds`,
`batches.py:155-161`), que hoy asume **un único presupuesto de malla global**
(`operaciones × 60 / admin_rate_limit_per_minute`). Si el límite de tasa pasa
a ser por-pasarela (§8), el cálculo correcto es: agrupar las operaciones
planificadas por `gateway_id`, calcular el ETA de cada grupo con SU propio
presupuesto, y tomar el **máximo** entre grupos (las pasarelas despachan en
paralelo, no en serie) en vez de sumarlas. Esto además hace el ETA más
honesto en instalaciones multi-pasarela reales (un lote sobre 2 mallas
independientes termina en, aproximadamente, el tiempo de la malla más lenta,
no en la suma de ambas).

---

## 8. Scheduler: ¿cola por pasarela, cola global, o combinación?

**Combinación — ya es así hoy, con un ajuste puntual.** La tabla
`admin_operations` es una única tabla física que actúa como N colas lógicas,
distinguidas por `gateway_id`. Esto ya es correcto y no se propone
cambiarlo (evita gestionar N tablas o N conexiones):

- La regla **"1 en vuelo por pasarela"** (`next_dispatchable`,
  `admin_repositories.py:92-115`, filtra por `gateway_id.not_in(busy)`) ya
  está correctamente delimitada por pasarela — no requiere cambios.
- El **límite de tasa** (`count_dispatched_since`,
  `admin_repositories.py:117-123`) hoy cuenta despachos de **todas** las
  pasarelas juntas (confirmado: la query no filtra por `gateway_id`). Con
  mallas físicamente independientes esto no tiene justificación regulatoria
  real (cada malla tiene su propio duty cycle EU_868/US915) y hace que N
  pasarelas compitan por un cupo pensado para una sola.

**Cambio propuesto**: escopar `count_dispatched_since` por `gateway_id`
(`WHERE gateway_id = :g AND queued_at >= :since`), de modo que cada pasarela
tenga su propia ventana de 60s independiente. `admin_rate_limit_per_minute`
sigue siendo un único valor de configuración (aplicado igual a todas las
pasarelas) — no se añade una columna de override por pasarela en esta fase
(YAGNI: nadie ha pedido pasarelas con presupuestos distintos; si aparece esa
necesidad, es una columna aditiva trivial de añadir después sin rediseño).

Este es, explícitamente, un **cambio de comportamiento** (aumenta el
throughput total con N pasarelas) y no puramente aditivo — se marca como
fase de riesgo medio que requiere confirmación explícita antes de fusionar
(§14, M6.5), a diferencia de los cambios puramente aditivos de datos/lectura.

---

## 9. Simulador: varias pasarelas simuladas a la vez

Confirmado por investigación: `SimulatedTransport` no tiene estado global
compartido (todo vive en `self._nodes`/`self._rng` por instancia,
`gateway/src/gateway/transports/simulated.py`), y la malla se genera
determinísticamente a partir de `GATEWAY_SIM_SEED` (por defecto 42). El
obstáculo real es puramente operativo (ya señalado así en la valoración
pre-M6, "arreglo trivial, no de código"): dos procesos con la misma semilla
generan la misma malla y se pisan en `nodes.gateway_id` (y ahora también en
`node_gateway_links`, aunque ahí al menos no se "pisan" — coexisten como dos
observaciones del mismo `node_id`, lo cual sería engañoso porque en
realidad serían dos nodos ficticios distintos con el mismo id por
coincidencia de semilla).

**No se propone** cambiar el valor por defecto de la semilla ni derivarla
automáticamente de `gateway_id` (evita alterar el comportamiento de
instalaciones/tests existentes que ya dependen del mesh determinista con
semilla 42). En su lugar, dos ajustes de superficie, coherentes con que M5 ya
movió la configuración de pasarelas del `.env` a la aplicación:

1. **`connection_params` para transporte `simulated`**: hoy
   `_PARAM_FIELDS["simulated"]` está vacío (`transport_manager.py:22-27`) —
   se amplía para aceptar `seed` y `node_count`, de modo que la semilla se
   pueda fijar desde el asistente de la app (`configure()`/`command.
   gateway_connect`) sin tocar variables de entorno por proceso.
2. **Sugerencia de semilla en el asistente "+ Añadir gateway"**: al
   configurar una nueva pasarela simulada, la UI propone (no fuerza) una
   semilla no usada por ninguna pasarela simulada ya registrada (consulta
   trivial sobre `gateways.connection_params`), evitando que el operador
   tenga que acordarse manualmente de no repetir semillas.

**Solape intencional para probar Multi-Gateway de verdad**: semillas
distintas dan mallas completamente disjuntas (útil para aislar, pero no
prueba la lógica N:M/selección de pasarela). Se añade un parámetro opcional
adicional, `shared_seed` (o reutilizar `GATEWAY_SIM_SHARED_SEED`), que genera
un subconjunto fijo de nodos "compartidos" (mismo algoritmo determinista,
semilla común) visibles por cualquier pasarela simulada que lo configure con
el mismo valor, además de sus nodos "exclusivos" de su propia semilla — esto
sí requiere un cambio de código en `_build_mesh()`, de bajo riesgo (aditivo,
por defecto sin solape si no se configura), y es el mecanismo concreto para
poblar `node_gateway_links` con casos de solape real en desarrollo/tests.

---

## 10. Actividad: eventos de varias pasarelas sin saturar

Cambios de UI, bajo riesgo, sin tocar contrato:

- El filtro de pasarela de `ActivityConsole.tsx` pasa de selección única a
  **multi-selección** (marcar/desmarcar varias pasarelas a la vez).
- Cada fila lleva ya `gateway_id` en el envelope — se añade una insignia
  compacta (nombre corto de la pasarela) visible en cada línea, para que con
  N pasarelas mezcladas el operador no tenga que abrir el detalle para saber
  el origen.
- Opción "agrupar por pasarela" (colapsada por defecto): agrupa ráfagas de
  eventos rutinarios (p. ej. heartbeats, `admin.operation` de despacho) por
  pasarela en una línea resumen expandible, igual que ya se deduplican los
  heartbeats de una sola pasarela hoy (`gateway.status`, solo transiciones).
  No cambia el buffer (sigue en 500 eventos, client-side).

---

## 11. Estadísticas nuevas gracias a Multi-Gateway

Directamente derivadas de `node_gateway_links` + límite de tasa por pasarela:

- **% de redundancia de cobertura**: proporción de nodos con ≥2 pasarelas
  activas simultáneas (vista general de salud de la malla, no solo por
  nodo).
- **Carga por pasarela**: operaciones/minuto usadas vs. cupo
  (`admin_rate_limit_per_minute` ahora por pasarela), profundidad de cola
  pendiente por pasarela — visibiliza si una pasarela concreta está saturada
  mientras otra está ociosa.
- **Comparación de señal cruzada** para nodos vistos por varias pasarelas:
  útil para detectar degradación de antena de una pasarela concreta (su RSSI
  hacia nodos compartidos cae mientras el de otra pasarela hacia los mismos
  nodos se mantiene).
- **Tasa de éxito de la selección de pasarela**: por operación, si terminó
  `succeeded`/`succeeded_unconfirmed` vs. `failed`/`timeout`, agregado por
  qué criterio del §6 decidió la pasarela (prioridad manual vs. hops vs.
  señal) — permite validar empíricamente si el orden de criterios elegido
  es el correcto y ajustarlo con datos reales más adelante.

Estas métricas dependen de M6.1 (datos) y M6.5 (rate limit por pasarela) —
no se implementan antes de tener esa base.

---

## 12. Compatibilidad con instalaciones de una sola pasarela

Diseño explícitamente pensado para migrar sin roturas:

- `node_gateway_links` es **aditiva**: migración de backfill trivial (una
  fila por nodo, copiando `gateway_id`/`rssi`/`snr`/`hops_away`/
  `last_seen_at` actuales) — una instalación de una sola pasarela queda con
  exactamente una fila por nodo en la tabla nueva, sin cambio de
  comportamiento observable.
- `nodes.gateway_id`/`rssi`/`snr`/`hops_away` **se conservan** con su
  significado actual (ahora explícitamente "pasarela primaria derivada"),
  así que ningún código existente que los lea se rompe.
- La función de selección de pasarela (§6) con un solo candidato es un
  no-op: siempre elige la única pasarela disponible, igual que hoy.
- El límite de tasa por-pasarela (§8) es indistinguible del actual cuando
  solo hay una pasarela (el conteo por-pasarela coincide con el global).
- El simulador no cambia su comportamiento por defecto (semilla 42 se
  mantiene como hoy si no se toca nada).

No hay, en ningún punto de este diseño, una migración destructiva ni un
cambio de contrato incompatible (`shared/events/` no necesita una versión
nueva del esquema: los campos que se leen en `node_gateway_links` ya viajan
hoy en el payload de `node.seen`).

---

## 13. Escalabilidad a futuros transportes (TCP, MQTT, BLE, remotas)

No requiere cambios de arquitectura adicionales a los ya descritos — es una
reafirmación, no una decisión nueva:

- Una pasarela se identifica por `gateway_id` con independencia de su
  `transport_type` (ya es una columna existente desde M5); todo lo diseñado
  aquí (N:M de observación, selección de pasarela, rate limit por-pasarela,
  streams `noc:commands:<gateway_id>`, eventos etiquetados con `gateway_id`
  en el canal único `noc:events`) es agnóstico del transporte subyacente.
- Pasarelas remotas (otra ubicación física) ya funcionan con el diseño
  actual siempre que tengan conectividad a Redis — es una preocupación de
  despliegue/red (exponer Redis de forma segura, VPN, etc.), no de
  arquitectura de aplicación.
- BLE/MQTT como transportes nuevos solo necesitan su propia clase
  `Transport` (como ya exige ADR 0002/0009) y, si aportan campos de señal
  distintos (p. ej. MQTT no tiene RSSI/SNR reales), `node_gateway_links`
  simplemente queda con esos campos en `NULL` para esa pasarela — el modelo
  ya contempla nullability en RSSI/SNR/hops (algunos nodos vía MQTT ya
  cursan sin estos datos hoy, campo `via_mqtt` existente).

---

## 14. Plan de implementación por fases

Ordenado por riesgo (aditivo/reversible primero, cambios de comportamiento
después) y con el menor impacto posible sobre lo ya validado.

- **M6.1 — Modelo de datos (bajo riesgo, puramente aditivo)**
  Tabla `node_gateway_links` + migración de backfill. Ingesta: upsert en
  `node.seen` (además del upsert monovaluado actual, sin quitarlo).
  Recalcular `nodes.gateway_id`/`rssi`/`snr`/`hops_away` con la política de
  §1.3/§3 en el mismo upsert. Endpoint de solo lectura
  `GET /nodes/{id}/gateways`. Sin cambios de contrato v1, sin tocar admin ni
  alertas todavía. Test de regresión explícito para el comportamiento ya
  correcto de `node_offline` (§5.1).

- **M6.2 — Dashboard y mapa (bajo riesgo, solo lectura)**
  Badge de redundancia + lista de pasarelas activas en panel de nodo y popup
  de mapa, usando el endpoint de M6.1. Sin cambios de backend adicionales.

- **M6.3 — Alertas: nueva regla opcional (bajo riesgo, aditivo, off por
  defecto)**
  `node_gateway_link_stale` (§5.2), desactivada por defecto, mismo motor de
  reconciliación existente (ADR 0012), sin tocar evaluadores existentes.

- **M6.4 — Selección de pasarela para administración remota (riesgo medio)**
  Función pura de selección (§6) sustituyendo el uso directo de
  `nodes.gateway_id` en `BatchService.create()` y en
  `remote_flag_sync.to_planned_operations()` (activa el campo
  `target_gateway_id` ya reservado desde ADR 0020). Override manual en UI
  cuando hay ≥2 candidatos. Requiere tests exhaustivos dado que ADR 0013
  prohíbe explícitamente doble ejecución — revisar con el usuario antes de
  fusionar por tocar el pipeline crítico de administración remota.

- **M6.5 — Límite de tasa por pasarela (riesgo medio, cambio de
  comportamiento explícito)**
  Escopar `count_dispatched_since` por `gateway_id` (§8). Se marca aparte de
  M6.4 porque cambia el throughput total del sistema (aumenta con N
  pasarelas) — requiere aprobación explícita del usuario antes de activarlo,
  no solo revisión técnica.

- **M6.6 — ETA de lotes multi-pasarela (bajo riesgo, depende de M6.4/M6.5)**
  Agrupar `estimate_seconds`/`progress()` por `gateway_id` y tomar el máximo
  entre grupos (§7).

- **M6.7 — Simulador y UX de alta de pasarelas (bajo riesgo, aislado)**
  `connection_params.seed`/`node_count` para transporte simulado, sugerencia
  de semilla no repetida en el asistente, solape opcional vía
  `shared_seed` (§9), y arreglo del obstáculo #4 (`GatewaysView.tsx:338`):
  selector explícito cuando hay ≥2 candidatos sin gestionar en vez de
  `Array.find` sobre el primero.

- **M6.8 — Estadísticas (bajo riesgo, depende de M6.1 + M6.5)**
  Métricas de redundancia, carga por pasarela y comparación de señal
  cruzada (§11).

- **M6.9 — Extensiones futuras, fuera de alcance de esta ronda** (mencionar,
  no implementar salvo que el usuario lo pida explícitamente después):
  serie temporal append-only de RSSI/SNR por pasarela para gráficas de
  tendencia; failover automático de pasarela a mitad de una operación ya en
  curso; ajuste automático de `priority` a partir de la tasa de éxito
  observada (§11); líneas gateway↔nodo en el mapa; overrides de límite de
  tasa por pasarela individual.

---

## 15. Preguntas abiertas para el usuario antes de arrancar M6.1

1. ~~¿Confirma el orden de criterios de selección de pasarela del §6?~~
   **Resuelto**: prioridad manual → saltos → SNR → RSSI → recencia,
   reutilizado también como ranking de pasarela primaria (§3).
2. ¿La nueva regla de alerta `node_gateway_link_stale` (§5.2) se quiere ya en
   M6, o se pospone hasta tener datos reales de instalaciones con ≥2
   pasarelas que justifiquen su utilidad?
3. ¿Aprueba explícitamente el cambio de comportamiento de M6.5 (límite de
   tasa por pasarela, aumenta el throughput total) para incluirlo en esta
   ronda, o prefiere dejarlo para una fase posterior una vez validado M6.1–M6.4
   con hardware real?

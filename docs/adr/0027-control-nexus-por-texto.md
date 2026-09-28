# ADR 0027 — Control de nodos JenTastic-Nexus por comandos de texto

- Estado: Aceptado (2026-09-29) — §1-§13 implementados: núcleo puro,
  transporte, cola de operaciones (con UI en Ajustes → JenTastic-Nexus y en
  pestaña propia del Inspector), interruptor global, detección de nodos
  JT, perfil de nodo, autorización SECURITY/ALLOW_DM, gato en el Mapa,
  TODOS los formatos de la lista original con parser real confirmado por
  captura, difusión con respuestas individuales por nodo, catálogo
  explorable por categorías, ocultación de la administración nativa que
  Nexus cubre al 100%, y ajustes configurables del módulo (incluido
  `-device` reincorporado como opción consciente, ya no bloqueado por
  defecto). Pendiente real: solo el presupuesto de tiempo de aire
  compartido con ADR 0013 (§4), dejado tal cual por decisión explícita
  del usuario.
- Complementa: ADR 0013 (pipeline de operaciones remotas), ADR 0006 (contrato
  de eventos versionado), ADR 0002 (solo el gateway importa `meshtastic`)
- Diseño asociado: `docs/design/nexus-control.md`

## Contexto

JenTastic-Nexus es un firmware Meshtastic modificado cuyos nodos se
administran enviándoles **mensajes de texto** (`/nexus ...`) por un canal de
confianza (`Nexus`/`JenT`), no con `AdminMessage` + PKC como el resto de la
administración remota de MeshSentinel (M1–M4). El usuario quiere usarlo como
método principal de administración de los nodos que corren ese firmware,
**separado** de la administración nativa (nunca mezclados en el mismo
formulario ni en el mismo transporte) y **detrás de un interruptor global**
que, apagado, hace que el módulo no exista.

Las respuestas llegan como texto normal (a veces paginado `P1:/P2:`), sin id
de petición, con posibles copias duplicadas y con jitter en difusión.

## Decisión

### 1. Núcleo puro en `backend/src/noc/application/nexus/`

Construcción de comandos, reensamblado, deduplicación, espaciado, correlación
y parseo son **funciones/clases puras** (sin red, BD, FastAPI ni
`meshtastic`; un test verifica los imports). Viven en el backend, no en el
gateway: el gateway solo transporta texto; toda la semántica Nexus queda en
un solo sitio y se testea sin hardware.

### 2. Catálogo cerrado

Solo los comandos del documento de referencia. Excluidos FSIG (vigencia
dudosa, pendiente de verificación manual) y AIRTAG (incompleto). Alias
ambiguos (`RL`) no se registran. Prefijo fijo `/nexus`; un nodo concreto se
direcciona con `-device !id`. NAME/OWNER/REVERT se rechazan en difusión **y
en grupo** (el firmware solo documenta el bloqueo en difusión; un grupo es
igual de catastrófico).

### 3. Transporte: `command.send_text` (implementado 2026-09-29)

Ya existía en `command.schema.json` desde la Fase 0 (nunca implementado).
Payload `{"text": str}` — sin `channel_index`: el gateway detecta
**siempre** el canal llamado "Nexus"/"JenT" (insensible a mayúsculas) en su
nodo local (`MeshtasticStreamTransport._find_nexus_channel`, ADR 0023 — un
solo sitio, heredado por USB/TCP) y usa `sendText`; sin ese canal, rechaza
en logs en vez de mandar "casi acertar" por el canal principal. Simulador:
`SimulatedTransport._simulate_send_text` responde a `INFO` desde nodos
distintos del local con el formato real de campo, para poder probar el
flujo de detección sin hardware. Las respuestas ya llegaban por
`message.received` sin tocar el decoder — y se persisten en `chat_messages`
(monitor de Chat, ya existente) sin cambios.

### 4. Cola propia para operaciones arbitrarias (implementado 2026-09-29)

Tabla `nexus_operations` (migración 0022) + `NexusOperationService`
(`application/nexus_operations.py`). Deliberadamente NO reutiliza el
pipeline de administración (ADR 0013): ahí el gateway reporta un resultado
estructurado por `admin.operation` (`running`/`succeeded`/`failed`); en
Nexus el gateway **nunca** reporta nada — solo transmite el texto
(`sendText`, fire-and-forget, igual que el propio firmware). Toda la
correlación es responsabilidad del backend, escuchando `message.received` y
reconstruyendo con el núcleo puro de §1-§2 (`CommandPacer` +
`ResponseAssembler` + `ResponseCorrelator` + `parse_response`) — un estado
en memoria POR PASARELA (`_GatewayState`), nunca persistido (efímero por
diseño, igual que los `_waiters` de `GatewayService`/`NexusGateway`; una
respuesta que llega tras un reinicio del backend a una operación enviada
antes se pierde sin más, la operación pasa a "sin respuesta").

Ciclo (scheduler propio, tick cada 2 s, sin relación con el de ADR 0013):
1. **Vigilante**: `sent` sin respuesta pasado el margen
   (`DEFAULT_RESPONSE_WINDOW_SECONDS` + `busy_seconds` de la operación) →
   `no_response`, terminal (una respuesta tardía nunca la reabre).
2. **Despacho**: recorre TODAS las `pending` de cada pasarela (no "1 en
   vuelo": el manual confirma que varios envíos dirigidos a destinos
   distintos no se bloquean entre sí) comprobando
   `CommandPacer.next_allowed_at()` antes de mandar cada una.
3. **Correlación**: cada `message.received` de una pasarela con operaciones
   activas se alimenta a su `ResponseAssembler` (páginas `P1:/P2:`, dedupe);
   cada respuesta completa pasa por `ResponseCorrelator.match()` — sin
   candidato, se ignora en silencio (tráfico ajeno, ecos del propio
   comando). Con candidato: `parse_response()` y `confirmed`.

Vocabulario de operador (M4.1, mismo criterio): Pendiente/Enviado/
Confirmado/Sin respuesta — nunca vocabulario del pipeline de administración
(`succeeded_unconfirmed` etc., modelo distinto). Destinos: broadcast/local/
node(shortname)/mac/group — `-device` deliberadamente ausente (§0.2:
deshabilitado). API: `POST/GET /nexus/operations`, `GET /nexus/operations/
{id}`, gateados por el interruptor global como el resto del módulo.
20 tests nuevos, todos con tiempo controlado explícitamente (nunca dormir de
verdad) — un bug real de la propia implementación se atrapó así: `handle_event`
usaba el reloj real en vez de aceptar `now` inyectable, haciendo la
correlación no determinista en tests (y en producción, sin defecto real: el
reloj real siempre fue correcto ahí, el problema era solo de testabilidad).

**UI implementada** (mismo día, `NexusOperationsPanel` en Ajustes →
JenTastic-Nexus, bajo la detección): formulario (pasarela, tipo de destino
broadcast/local/node/mac/group, comando, argumentos) → `POST /nexus/
operations/preview` (dry-run, sin persistir — mismo patrón que M2
"simular→CONFIRMAR") muestra el texto exacto y, si `destructive`, exige
teclear el destino (o "BROADCAST") antes de habilitar "Encolar" (mismo
patrón M1.3) → historial con polling de 3 s, vocabulario de operador
(Pendiente/Enviado/Confirmado/Sin respuesta) y fila expandible con la
respuesta cruda + `response_data` si el parser la reconoció. Vive en
Ajustes Y (desde §8) en una pestaña propia del Inspector de cada nodo
Nexus — mismo formulario, mismo endpoint, sin duplicar lógica de backend.

**Pendiente**: el presupuesto global de tiempo de aire compartido con
ADR 0013 (hoy los dos pipelines tienen presupuestos completamente
independientes).

### 5. Interruptor global y marcado manual (implementado 2026-09-29)

`nexus_mode_enabled` en `system_settings` (reutiliza la tabla clave/valor
genérica de la fase de Ajustes, migración 0020 — sin migración propia para
el flag) + columna `nodes.is_nexus` (migración 0021) marcada solo a mano
(nunca autodetectada; `_NODE_SIGHTING_FIELDS` no la incluye — los upserts
de avistamiento no la tocan, cubierto por test). Guard clause en cada
endpoint del router `nexus.py` salvo `GET /mode` (el frontend lo necesita
para decidir si carga el módulo); con el flag OFF, `POST /scan` devuelve
404 antes de tocar el gateway.

### 6. Detección de nodos JT — solo sugiere (implementado 2026-09-29)

`POST /nexus/scan` (ADR 0027 §8/D1 del prompt v2.8.006): construye
`/nexus INFO` con el catálogo puro (`build_command`), lo encola como
`command.send_text`, espera una ventana (30 s por defecto) y relee
`chat_messages` — **reutiliza el monitor de Chat ya persistido en vez de
montar una correlación en vivo aparte** (más simple y robusto: sobrevive a
un reinicio del proceso a mitad de espera). Filtra por CONTENIDO
(`parse_response("INFO", texto).kind == "structured"`, núcleo puro), no por
canal — el backend no sabe qué índice auto-detectó el gateway, y filtrar
por contenido ya descarta con seguridad tráfico ajeno (confirmado con un
"Pong" real de otro sistema capturado por casualidad durante las pruebas de
campo). Devuelve candidatos (`node_id`, nombre corto, versión, rol,
marcador 🟢/🔴 de firma) marcando cuáles ya están aceptados
(`already_marked`) — **nunca escribe `is_nexus`**: el operador confirma
cada uno por separado vía `PUT /nodes/{id}/nexus` (mismo endpoint que el
marcado manual directo, sin escanear). Límite de cadencia de 2 min por
pasarela en memoria del proceso (cortesía de tiempo de aire, no garantía
distribuida). UI: sección "JenTastic-Nexus" en Ajustes (solo
administradores) — interruptor + selector de pasarela + tabla de
candidatos con Marcar/Descartar por fila, sin atajo de "marcar todos" a
propósito. Decisión del usuario, tras verificar que el encargo original
(§8 y D1-D5) pedía exactamente esto y no auto-marcado, pese a que el primer
pedido de esta fase lo pedía literalmente ("auto marcas") — confirmado con
el usuario antes de implementar.

### 7. Parsers SECURITY/SETTINGS/FSIG/LORA-STATUS (captura real, 2026-09-28)

Segunda tanda de captura real (mismos dos nodos, ya en firmware 2.8.005,
`tools/nexus_capture.py`) resolvió cuatro de los formatos que quedaban
pendientes en la iteración 1: `parse_security`, `parse_settings`,
`parse_fsig`, `parse_lora_status` (`application/nexus/parsers.py`). Detalle
completo en `docs/design/nexus-control.md` §0.3. Hallazgo relevante: la
respuesta real de `SECURITY` trae 3 campos más de los que el manual v2.8.006
documenta para la build pública (`FAV_NX`/`FAV_TR`/`BYPASS_RP`, que el
manual llama `AUTO_FAV_NEXUS`/`AUTO_FAV_TRUSTED`/`BYPASS_RP` y da por
AUSENTES ahí) — **no es un error del manual**: el usuario confirmó que los
dos nodos de prueba corren la build PRIVADA/táctica, la misma familia de
extensiones ya excluida del catálogo por nombre de comando (`BURNER` etc.,
§2). El parser expone los 6 campos tal cual el firmware los llama, sin
asumir cuáles son "públicos" — sigue funcionando igual si algún día se
prueba contra un nodo de build pública real (manda solo 3). `WATCH STATS`
sigue pendiente: la única captura disponible (subsistema WATCH vacío)
devolvió el texto de ayuda genérico, no datos.

### 8. Pestaña "JenTastic-Nexus" en el Inspector (implementado 2026-09-29)

Cierra el punto 7 del encargo original. `Inspector.tsx` gana una pestaña
`nexus` junto a la ya existente `operations` (pipeline nativo AdminMessage/
PKC, ADR 0013) — visible SOLO cuando se cumplen las dos condiciones a la
vez (mismo criterio que la insignia del gato, §6): interruptor global ON Y
este nodo marcado (`showNexusTab = nexusModeOn && n.is_nexus`). Si deja de
cumplirse mientras la pestaña estaba activa (se desmarca el nodo, se apaga
el flag), cae a "Actividad" en vez de quedarse en una pestaña fantasma
(`effectiveTab` filtra contra `visibleTabs`, no confía en el `tab`
persistido/de URL).

Contenido nuevo (`components/nexus/NodeNexusPanel.tsx`): el mismo flujo
previsualizar→confirmar→encolar de `NexusOperationsPanel` (Ajustes), pero
con el destino FIJO a este nodo (`-node <shortname>`, el único
direccionamiento dirigido soportado, §0.2) — quien abre esta pestaña ya
eligió el nodo, no tiene sentido volver a pedirlo. Reutiliza el mismo
endpoint `POST /nexus/operations/preview`/`POST /nexus/operations`, cero
lógica de backend nueva. Historial filtrado client-side por
`target_kind === "node" && target_value === shortName` sobre
`GET /nexus/operations` (sin gateway fijo: un nodo puede responder a
distintas pasarelas). Vocabulario de operador reutilizado tal cual
(`STATUS_LABELS`/`STATUS_COLORS`, exportados de `NexusOperationsPanel.tsx`
para no duplicarlo). tsc/build limpios, 512 tests backend+gateway sin
regresión (cambio solo de frontend).

### 9. Perfil de nodo (SETCONFIG), autorización SECURITY/ALLOW_DM y gato en el Mapa (2026-09-29)

Cierra los puntos 4 (perfil de nodo), 3 (autorización) y la insignia visual
pendiente del encargo original, más el parser parcial de FIREWALLSTATS.

- **`NodeNexusSecurity`** (`components/nexus/NodeNexusPanel.tsx`): botón
  "Leer estado" (encola `SECURITY` sin argumentos, consulta pura) + chips
  con el bitmask de la última lectura CONFIRMADA (mismo criterio que
  M4.1/M4.2: sin SET remoto no hay forma de releer la NodeDB por cuenta
  propia para verificar). Si `ALLOW_DM` está `off`, aviso + botón que
  PRECARGA el formulario genérico con `SECURITY ALLOW_DM on` — nunca lo
  envía por sí solo, el operador sigue teniendo que previsualizar y
  encolar como con cualquier otro comando.
- **`NodeNexusProfile`**: mismo patrón para `CONFIG`/`SETCONFIG`, con
  sintaxis confirmada por captura real (§0.4 de `docs/design/nexus-
  control.md`): `SETCONFIG <CAMPO> <valor>` uno a uno (NI/TEL_D/TEL_E/
  TEL_P/POS/SMART/FIXED/GPS) + `SETCONFIG LOC lat,lon`. Rol y LoRa manual
  (SF/BW/CR/Freq) NO son editables: `SETROLE`/`SETLORA` no existen en el
  firmware probado (`JT: Unknown command`, build privada) pese a que
  `SETLORA` estaba catalogado como confirmado — no se puede ofrecer un
  botón para un comando que el propio nodo rechaza; Rol se muestra de solo
  lectura.
- **`FIREWALLSTATS` parser parcial** (`parsers.py`): las 6 líneas iniciales,
  sin etiquetas repetidas, se estructuran igual que `STATS`; el resto
  (`Port:`/`RL Seen`/`RL Pass`/`RL Drop`/`Trace`, que sí repiten la misma
  etiqueta para sub-campos distintos) se deja tal cual, como texto, bajo
  `extra_raw` — nada se pierde, solo no se etiqueta lo que no se puede
  etiquetar sin inventar.
- **Insignia del gato en el marcador del Mapa**: `NEXUS_CAT_RECTS` extraído
  a una única fuente de geometría en `NexusCatIcon.tsx`, de la que salen
  tanto el componente React (Flota/Inspector) como `nexusCatMarkup()` (el
  HTML crudo que necesitan los `L.divIcon` de Leaflet, que no pueden
  montar JSX) — mismo icono en los tres sitios, nunca redibujado a mano.

514 tests backend+gateway, ruff/tsc/build limpios. Sin cambios de
arquitectura ni de contrato — todo sobre la infraestructura ya existente
(preview/confirm/encolar, `system_settings`, `nodes.is_nexus`).

### 10. WATCH completo, FSIG SET/OFF y FIREWALLSTATS completo (2026-09-28/29)

Cierra la lista original de formatos pendientes por completo. Detalle en
`docs/design/nexus-control.md` §0.5-§0.8.

- **`WATCH LIST`/`ADD`/`DEL`/`STATS`**: los tres primeros con captura real
  directa; `STATS` necesitaba el node_id vigilado como argumento
  (`WATCH STATS <hex8>`) — lo detectó el propio usuario probándolo en
  directo con hardware ("Hice /nexus watch stats !af000001 y funciona, tras
  haber hecho watch add !id"), confirmado después con captura formal.
  Respuesta real con RF (dB+SNR+FE)/Hops/Relay/Timing/Ports; `Min:`/`Max:`
  aparecen dos veces en el texto (RF en dB, Timing en segundos) —
  distinguidos por el sufijo de unidad en el propio patrón, cada sección en
  su grupo anidado, sin colisión.
- **`FSIG SET <1-8> <patrón>` / `FSIG OFF <1-8>`**: confirmados con
  hardware real (slot de prueba, restaurado al final). `parse_fsig`
  reescrito: cada slot pasa de string plano a
  `{"active", "pattern"?, "encoding"?, "bytes"?}`.
- **`FIREWALLSTATS` completo**: la ambigüedad de etiquetas repetidas
  (`Port:` ×3, `RL Seen/Pass/Drop` ×2, `Trace` ×2) se resolvió sin
  necesitar una segunda captura — no era una ambigüedad de VALORES, era de
  posición: `extra_sections` es una lista ordenada de una entrada por
  línea, nunca fusionadas entre sí, así que etiquetas repetidas conviven
  sin colisionar. Un único caso queda sin capturar a propósito (`HOP: 6:0
  7:0`, pares compuestos indistinguibles de un valor suelto sin adivinar).

521 tests backend+gateway, ruff limpio.

### 11. Difusión/grupo con respuestas individuales por nodo (implementado 2026-09-29)

Pedido explícito del usuario: al mandar un comando Nexus a toda la flota
(vía difusión — "van a responder todos ese comando uno a uno con su
estado y sus cambios"), quiere ver la respuesta de CADA nodo por
separado, no un único estado agregado por operación (el modelo original
de §4 daba por terminal la PRIMERA respuesta que llegaba, descartando el
resto — correcto para destino único, insuficiente para difusión).

El núcleo puro (`correlation.py`) ya lo permitía sin tocarlo: `match()`
nunca retira un candidato de la lista de pendientes al acertar, solo por
expirar su ventana — así que múltiples respuestas dentro de la ventana
YA se correlacionaban todas con el mismo `command_id`. El único cambio
necesario fue en la capa impura (`application/nexus_operations.py`):

- Migración 0023: `nexus_operation_responses` (append-only, `operation_id`
  FK + `from_node_id` + `received_at` + `response_text`/`kind`/`data`).
  `nexus_operations.response_*` (0022) sigue siendo el único-y-terminal
  para destinos DIRIGIDOS (local/node/mac) — sin cambios ahí.
- `_resolve()`: para `target_kind` en `{broadcast, group}`
  (`FANOUT_TARGET_KINDS`), cada match INSERTA una fila en la tabla nueva
  en vez de marcar la operación terminal — la operación se queda "sent"
  (escuchando) hasta que expire su ventana.
- `_expire_stuck()`: al cerrar la ventana de una operación de destino
  múltiple, cuenta sus respuestas — "confirmado" si ≥1, "sin respuesta"
  si 0. Las de destino único siguen su comportamiento de siempre.
- API: `GET /nexus/operations/{id}/responses`.
- Frontend: la fila de historial de una operación de difusión/grupo
  expande a la lista de respuestas por nodo (`FanoutResponses`,
  `NexusOperationsPanel.tsx`), con polling de 3 s mientras esté abierta.

4 tests nuevos en `test_nexus_operations.py` (difusión con 2+ respuestas,
cierre por ventana con respuestas, grupo con 2+ respuestas, destino
dirigido comprobado explícitamente intacto). 525 tests backend+gateway,
ruff/tsc/build limpios.

### 12. Catálogo completo explorable y ocultación de administración nativa superada (2026-09-29)

Dos piezas más del mismo encargo del usuario:

- **`GET /nexus/catalog`**: expone los 186 comandos de `catalog.py`
  (nombre, categoría, alias, si muta, destructivo, tiempo de ocupación,
  si está bloqueado en difusión) para que la UI ofrezca un EXPLORADOR por
  categorías (`NexusCatalogBrowser.tsx`, filtro por nombre/alias) en vez
  de un campo de texto libre que exige saberse el comando de memoria —
  integrado tanto en Ajustes → JenTastic-Nexus como en la pestaña del
  Inspector. Elegir un comando solo rellena el campo, nunca envía nada
  por sí mismo — sigue habiendo que previsualizar y confirmar.
- **Ocultación de administración nativa superada** (`nativeOverlap.ts`):
  decisión explícita del usuario tras aclarar el alcance — SOLO las dos
  operaciones donde Nexus cubre el 100% de lo que hace la nativa
  desaparecen del selector de `NewOperationForm.tsx` cuando el nodo
  elegido está marcado Nexus y el modo global está activado:
  `owner.set` (↔ Nexus `NAME`/`OWNER`) y `position.set_fixed` (↔ Nexus
  `SETCONFIG FIXED`+`SETCONFIG LOC`, sintaxis confirmada por captura
  real, §0.4). Deliberadamente CORTA: `config.set`/`module_config.set`
  cubren decenas de secciones (LoRa, Bluetooth, pantalla, red...) de las
  que `SETCONFIG` solo alcanza 8 campos — esas se quedan SIEMPRE
  disponibles, nunca se oculta una operación que Nexus solo cubre a
  medias. Un aviso visible explica por qué desaparecieron esas dos
  opciones y dónde encontrarlas.

### 13. Ajustes del módulo, `-device` reincorporado como opción (2026-09-29)

Pedido explícito del usuario: "en los ajustes, al pinchar en activar
Nexus, quiero ajustes debajo" — con dos ejemplos concretos: elegir cómo
dirigirse a un nodo (id o nombre corto) y el comando/prefijo a usar. El
resto de ideas del brainstorm ("todo lo demás adelante") también entraron.

- **`-device` reincorporado** (`builder.py`): la prohibición dura que
  levantaba `NexusCommandError` (§0.2, decisión de 2026-09-28 tras 20
  pruebas de campo sin respuesta) se retira — el usuario confirmó conocer
  la causa exacta ("eso falló porque al actualizar mi nodo se cambió el
  id") y quiere la opción de todos modos. La política de "cuál es el
  seguro por defecto" se mueve por completo a la capa de ajustes: el
  núcleo puro ya no impone nada, solo modela el protocolo (`Device` ya
  era una primitiva real de `addressing.py`, ahora simplemente utilizable
  desde `target_from()`). `addressing_mode` (`shortname`|`device_id`)
  controla ÚNICAMENTE qué opción viene preseleccionada — en el formulario
  de Ajustes y en la pestaña Nexus de cada nodo (Inspector) — el operador
  siempre puede elegir la otra a mano, con un aviso visible del riesgo
  conocido cuando usa `device_id`.
- **`application/nexus_settings.py`** (nuevo, sin migración — reutiliza
  `system_settings` con claves `nexus.*`, mismo patrón que
  `nexus_mode_enabled`): registro de 11 ajustes heterogéneos (texto,
  número, booleano, listas) con su propia validación — deliberadamente
  SEPARADO de `settings_registry.py` (umbrales numéricos atados a
  `noc.config.Settings`, un modelo distinto). `GET/PATCH /nexus/settings`
  (PATCH admin-only, parche parcial, falla entero si una clave no vale —
  nunca a medias).
- **Ajustes con efecto real, leídos en vivo** (sin caché, coste marginal
  por ser una fila indexada por PK, mismo criterio que
  `is_mode_enabled()`): `command_prefix` (`build_command`, tanto en
  operaciones como en el `/nexus INFO` de detección),
  `response_window_seconds` (ventana del vigilante de sin-respuesta Y del
  `ResponseCorrelator` de cada pasarela — esta última solo aplica a
  pasarelas que empiecen a despachar DESPUÉS del cambio, el estado en
  memoria ya activo no se retroactúa), `scan_cooldown_seconds` (cadencia
  del botón "Buscar nodos JT").
- **Ajustes de preferencia de UI** (sin efecto en el protocolo):
  `default_target_kind`/`default_gateway_id` (formulario de Ajustes →
  Operaciones), `catalog_collapsed_default` y `hidden_commands` (el
  explorador de catálogo, checklist de los 186 comandos — nunca oculta el
  comando del catálogo real del backend, solo de lo que se OFRECE en el
  explorador), `pinned_nodes` (atajos de nodo con etiqueta) y `templates`
  (comando+argumentos guardados) como chips de un clic en el formulario
  de Ajustes, y `notify_on_broadcast_complete` (toast cuando una difusión
  termina de recibir respuestas — detectado por comparación entre polls
  del historial, sin evento WS dedicado, ADR 0027 §4/§11 no tiene uno).

547 tests backend+gateway (10 nuevos: `test_nexus_settings.py` + 2 en
`test_nexus_operations.py`, incluido el flip de
`test_create_rejects_device_targeting` →
`test_create_accepts_device_targeting`), ruff/tsc/build limpios.

- **`channel_name`** (mismo registro de `nexus_settings.py`): por defecto
  `None` mantiene la autodetección de `meshtastic_stream.py` por nombre
  ("Nexus"/"JenT", insensible a mayúsculas); con un nombre fijado, el
  backend lo manda en `payload.channel_name` de `command.send_text` y el
  gateway busca EXACTAMENTE ese canal — nunca por índice fijo, mismo
  criterio de diseño — rechazando el envío si no existe en vez de usar el
  canal principal. Control nuevo en Ajustes → JenTastic-Nexus ("Canal de
  salida de comandos").
- **Alias de cabecera `Nexus <X>:` = `JT <X>:`** (`parsers.py`,
  `_first_line` y el regex de `parse_version`): el usuario capturó tres
  respuestas reales a `/nexus INFO` de nodos con firmware distinto en la
  misma malla — 2.7.268 y 2.8.005 responden `JT INFO:`, pero 2.7.265
  respondió `Nexus INFO:` (mismo contenido, cabecera de nomenclatura
  vieja). Sin este alias esa respuesta caía a `kind="raw"` y el nodo no
  se detectaba como candidato en `/nexus/scan`. Generalizado a todos los
  comandos que pasan por `_first_line` (no solo INFO), por decisión
  explícita del usuario ante la duda.

## Consecuencias

- Todos los formatos de la lista original ya tienen parser real confirmado
  por captura (§7/§9/§10) — no queda ningún comando del encargo mostrándose
  como texto plano por falta de dato real.
- El fin de una respuesta paginada se detecta por silencio (8 s) porque se
  desconoce si la cabecera indica el total; ajustable al tener capturas.
- Correlación por ventana de tiempo: si dos operadores mandan comandos al
  mismo nodo a la vez fuera de MeshSentinel, una respuesta puede asociarse al
  comando equivocado. Riesgo asumido (no hay id de petición en el firmware).

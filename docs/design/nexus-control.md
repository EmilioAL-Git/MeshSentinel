# Control JenTastic-Nexus — diseño del módulo

Estado: iteración 1 (núcleo puro) implementada y reconciliada contra el
manual oficial v2.8.006. Iteración 2 completa (2026-09-29): interruptor
global, detección de nodos JT, cola de operaciones (Ajustes + Inspector con
pestañas Radio/LoRa vs JenTastic-Nexus) — detalle completo en ADR 0027
§3/§4/§5/§6/§8, no duplicado aquí. Sigue pendiente: presupuesto de tiempo de
aire compartido con ADR 0013, y los formatos sin captura real listados en
§0.3. Fuentes del núcleo puro, por orden de prioridad ante conflicto (el
usuario lo pidió así explícitamente):
1. **`Manual Nuevo JT.pdf`** ("Nexus Commands Reference — Public Build",
   Nexus-28006/v2.8.006+, se declara "verified directly against the C++
   source code") — llegó el 2026-09-28, **fuente principal desde ahora**.
2. `Prompt_Implementacion_Nexus_StatisticSentinel.md` — resumen previo de
   ese mismo manual, ya superado donde el PDF real lo contradice.
3. `JenTastic-Nexus_Integracion_StatisticSentinel.md` (v2.8.005-Nexus) —
   referencia original, la menos fiable de las tres.

## 0.0 Reconciliación completa contra el manual real (2026-09-28)

Con el manual ya en mano se revisó `catalog.py`/`pacing.py`/`addressing.py`
entero contra su índice alfabético (§15, ~150 comandos) y sus tablas
detalladas. Cambios de comportamiento reales, no solo de catalogación:

- **Cooldown de difusión NO se aplica a envíos dirigidos.** El manual (§1,
  tabla de prefijos) es explícito: `-device`/`-node` "Bypasses broadcast
  cooldown". `pacing.py` aplicaba antes el cooldown de 5 s a TODO envío
  (decisión propia sin fuente, ahora corregida) — solo se aplica entre
  difusiones/grupos consecutivos; el espaciado de 10 s por destino (decisión
  del usuario, no del firmware) se mantiene igual para todo.
- **`<mac6>` son 6 caracteres hex (3 bytes)**, no 4 (2 bytes) como se había
  dejado sin confirmar — corregido en `addressing.Mac`.
- **`RL` deja de ser ambiguo**: es alias real de `RATELIMIT`; `RSSILOG` usa
  `PL`. Ambos registrados.
- **Renombrados/reemplazados** por la forma real: `INVALID`/`UNINVALID` →
  `INVALIDS` (un único comando `<RULE> [ON|OFF]`); `REBROADCAST` →
  `SETREBROADCAST`; `PRALLOW`/`PRBLOCK` pasan a ser ALIAS de
  `PRWHITELIST`/`PRBLACKLIST` (no comandos aparte — antes se habían dejado
  coexistiendo como si fueran independientes); `TA` es el nombre canónico
  (`TR_ALERT` no aparece en el manual).
- **Excluidos, confirmados ausentes de la build pública** ("private/tactical
  extension commands... intentionally omitted", ni en tablas ni en el
  índice): `BURNER`, `ROLEMASK`, `SETMULTIROLE`. También `ADDURL` y
  `USETCHNAME` (el "prefijo U salta protección de canales" no aparece en
  ningún sitio del manual).
- **Confirmados reales con sintaxis exacta**: `FSIG` (8 slots,
  `SET <1-8> <patrón>`/`OFF <1-8>`, auto hex/base64/texto, máx 16 bytes);
  `SECURITY` con solo 3 bits en build pública (`REQ_SIG`/`ALLOW_DM`/
  `SILENT_LOG` + contador `REP_Protection`) — `AUTO_FAV_NEXUS`/
  `AUTO_FAV_TRUSTED`/`BYPASS_RP` confirmados AUSENTES, no solo "sin
  verificar" como se dejó antes. **Corregido en §0.3**: la captura real
  contra un nodo 2.8.005 demuestra que los tres SÍ existen en el firmware
  (`FAV_NX`/`FAV_TR`/`BYPASS_RP`) — el manual se equivocaba en este punto
  pese a declararse "verified against the C++ source".
- **~20 comandos nuevos** añadidos al catálogo: `HELP`, `COMPILATION`, `HW`,
  `ACC`, `G3`, `SETTINGS`, `NODES28`, `MODULES`, `FEATURES`, `TM`,
  `FULLCONFIGDUMP`, `RATELIMITSTAT`, `GOODPRACTICES`, `OKTOMQTT`, `VAULT`/
  `VAULT DIFF`, `FREEZE`, `DBFLUSH`, `BSAVE`/`BLOAD`, `BD`, `SENSORS`,
  `MCUINFO`, `WIFIOTA`, `VERIFYSTATS`, `CRSTATS`, `RSSI`/`SHORTRSSI`/
  `RSSITEL`.
- **Marcador 🟢/🔴**: confirmado por el usuario tras verlo en campo — semáforo
  de si la firma del comando era válida (`REQ_SIG`). Aparece delante de
  `JT ...:` en más respuestas de las que se había visto (VERSION Y también
  INFO, confirmado con captura real) — bug real encontrado y corregido: el
  parser de INFO no lo esperaba y rechazaba la respuesta; generalizado a
  los 6 parsers que comparten `_first_line()`.
- **Pendiente de re-verificar con captura**: `NODES` — el manual describe un
  resumen corto de una línea ("JT NODES: X total (Y active)"), pero la
  captura contra firmware 2.7.268 dio un volcado paginado bajo cabecera
  "JT NodeDB:". Puede haber cambiado entre versiones de firmware; sin
  confirmar todavía contra 2.8.x (ver §0.1 más abajo).

## 0.1 Sesión de campo tras actualizar el T1000 a 2.8.005 (2026-09-28)

El usuario actualizó el nodo objetivo de las pruebas (T1000) de 2.7.268 a
2.8.005.f76ca88. Nota del usuario: **desde 2.8, el `node_id` se regenera a
partir de la clave pública** — puede cambiar al reflashear (pasó de
`!af000018` a `!af000002`; físicamente el mismo dispositivo).

Una tanda completa de 9 comandos de solo lectura contra el T1000 recién
actualizado no obtuvo NINGUNA respuesta (ni siquiera un rechazo) — se
sospechó un problema de direccionamiento (`-device` vs `-node`, que es como
el usuario dirige normalmente sus comandos). Diagnóstico con
`tools/nexus_diag_device_vs_node.py` (script de un solo uso, no forma parte
del módulo): las tres formas de direccionamiento (`-device`, `-node`,
difusión) SÍ funcionaron correctamente cuando se repitió la prueba minutos
después — el fallo original fue puntual, probablemente el nodo aún
asentándose tras el flasheo, no un bug del direccionamiento del módulo.
Conclusión: `-device`/`-node`/difusión están todos verificados como
funcionales contra un nodo real en 2.8.005.

No se llegó a repetir la tanda completa de 9 comandos (SECURITY/SETTINGS/
NODES/CONFIG/HW/ACC/RATELIMITSTAT/MODULES) tras confirmar el
direccionamiento — sigue pendiente para la próxima sesión con hardware.

## 0.2 `-device` deshabilitado; solo `-node <shortname>` (2026-09-28)

Se repitió la tanda (11 comandos: los 8 anteriores + FSIG e INFO) contra el
T1000 en 2.8.005. Resultado: **0 de 11 respuestas con `-device`**, igual que
la tanda anterior (20 intentos `-device` en total entre las dos sesiones, 0
respuestas salvo una única vez justo después de que el usuario interactuara
manualmente con el nodo). En la misma sesión, inmediatamente después,
`/nexus VERSION` (difusión) y `/nexus-node N019 UPTIME` (nombre corto)
**funcionaron los dos**.

Decisión del usuario, con motivo razonado: desde firmware 2.8 el `node_id`
se regenera a partir de la clave pública y puede cambiar en cualquier
momento — depender de él para direccionar es frágil por diseño, no un fallo
puntual de esta sesión. **`-device !id` queda deshabilitado en el módulo**:
`build_command` lo rechaza (`NexusCommandError`) si se le pasa un `Device`
como destino. `addressing.Device` se conserva como primitiva del protocolo
(sigue siendo real y documentada por el manual), pero ningún camino del
módulo la usa — todo direccionamiento a un nodo concreto pasa por
`ShortName` (`-node <shortname>`). `tools/nexus_capture.py` actualizado
igual (construye `/nexus-node <shortname> ...`, ya no `/nexus-device`).

Efecto colateral en iteración 2: cuando se implemente el marcado de nodos
"JenTastic-Nexus" (punto 8 del encargo), habrá que guardar también el
**nombre corto** del nodo, no solo su `node_id` — es lo único estable con lo
que el módulo puede dirigirse a él.

También se atrapó al vuelo un dato útil para los parsers futuros de
FIREWALLSTATS/NODES: en una captura llegó un mensaje `🏓Pong!🏓...` de un
sistema ajeno, oído por casualidad en OTRO canal (6, "Test") casi a la vez
que un comando propio — recordatorio de que cualquier parser/dedupe debe
comprobar el canal, no solo el contenido.

Bug real encontrado y corregido con la captura de esta tanda: el marcador
🟢/🔴 aparece también delante de `UPTIME`, no solo `VERSION`/`INFO` — ya
cubierto por el fix genérico de `_first_line()` de la sesión anterior, sin
cambios adicionales necesarios (confirma que la generalización fue
correcta).

## 0. Cambios de la fuente 2 ya aplicados al código

| Cambio | Antes (v2.8.005) | Ahora | Dónde |
|---|---|---|---|
| Límite de texto | 233 bytes (payload del protocolo) | **200 caracteres** (explícito, con caso real de corrupción) | `builder.MAX_TEXT_CHARS` |
| `FSIG` | Excluido (vigencia dudosa) | Registrado (8 slots, sin validación fina) | `catalog.py` |
| `PRALLOW`/`PRBLOCK` | Únicos | Coexisten con `PRWHITELIST`/`PRBLACKLIST` (v2.8.006) | `catalog.py` |
| `SETTINGS` | No existía | Comando real, distinto de `CONFIG` (SK:n/4) | `catalog.py` |
| `ZH IMPORT` | No modelado | Destructivo (sobrescribe la máscara completa) | `catalog.py` |
| `SETLORA` | No destructivo | Destructivo (modal) | `catalog.py` |
| `REBOOT` | No destructivo | Destructivo (modal) | `catalog.py` |
| `TX OFF` | Sin distinción de valor | Destructivo solo con `OFF` (`TX ON` no) | `catalog.py` |
| `SETSYNCWORD` | Sin distinción de valor | Destructivo salvo valor `0x2B` (el de fábrica) | `catalog.py` |
| `REDIRECT`/`R` | Sin límite de anidamiento | Profundidad máxima 2 | `builder._redirect_depth` |

Sin cambios pendientes de aplicar del prompt v2.8.006 que fueran inequívocos;
lo que falta (D, E3 exacto, F1-F4 UI, G) está en §7.

## 1. Decisiones del usuario (2026-09-27)

| Tema | Decisión |
|---|---|
| Formatos de salida (STATS, WATCH STATS…) | Parsers pendientes; se implementan uno a uno con capturas reales |
| `SETTINGS` | No existe en el documento; probablemente `CONFIG` |
| Paginación `P1:` | Formato por confirmar; fin por silencio mientras tanto |
| Canal de confianza | El gateway lo detecta automáticamente por nombre |
| Prefijo | Siempre `/nexus`; nodo concreto con `-device !id` |
| `ZH ADD/DEL` | Solo los 2 últimos caracteres hex (`!e53626b0` → `b0`) |
| Espaciado | MeshSentinel espacia siempre (el nodo necesita tiempo para responder) |
| Correlación | Último comando compatible dentro de una ventana |
| Firmware/OTA | Fuera de alcance |

## 2. Estructura

```
backend/src/noc/application/nexus/     (puro — test_module_is_pure lo vigila)
  addressing.py   prefijos, destinos (Broadcast/Local/Device/ShortName/Mac/Group),
                  parser tolerante de IDs, truncado ZH, is_command_text
  catalog.py      catálogo cerrado: alias, categoría, mutación, SAVE, destructivos,
                  bloqueados en difusión, busy_seconds; EXCLUDED = FSIG, AIRTAG
  builder.py      build_command(...) → NexusCommand (texto + banderas para la UI)
  pacing.py       CommandPacer: 5 s canal · 10 s por destino · tiempo ocupado
  reassembly.py   ResponseAssembler: P1/P2… por nodo, dedupe packet_id + texto (5 s)
  correlation.py  ResponseCorrelator: respuesta → command_id
  parsers.py      registro PARSERS (vacío) + PENDING_FORMATS; fallback a texto crudo
  ports.py        NexusTransport (Protocol)
backend/tests/test_nexus.py
```

Flujo previsto (iteraciones siguientes):

```
UI → API /nexus/* ─guard(flag)→ NexusService ─build_command→ cola persistente
     ─pacer→ NexusTransport → command.send_text → gateway.sendText(canal Nexus)
gateway → message.received ─guard(flag, canal Nexus, nodo is_nexus)→
     ResponseAssembler → ResponseCorrelator → parse_response → BD + WS
```

## 3. Semántica que ya aplica el núcleo

- **Destructivos (modal en la UI):** REVERT, NAME, OWNER, DELNODE, `ZH CLEAR`,
  `RDROP CLEAR`.
- **Bloqueados en difusión y grupo:** NAME, OWNER, REVERT.
- **Nodo ocupado ("aplicando…"):** FREQSCAN 15 s, REBOOT 20 s, SETLORA/
  SETPREAMBLE/SETSYNCWORD 5 s, NETSCAN 60 s. NAME/OWNER/REVERT 20 s
  (supuesto: reinician; por verificar).
- **Recordatorio SAVE:** todo comando que muta, salvo RATELIMIT (auto-
  persistente), identidad (reinicia), inyección, SAVE/LOAD, REBOOT/TX. Sin
  argumentos o con `LIST`/`STATS` = consulta, sin recordatorio. Criterio
  conservador: un recordatorio de más es inocuo, uno de menos pierde cambios.
- **Argumentos:** tokens libres (el firmware valida), pero nunca `;` ni saltos
  de línea (evita encadenar comandos sin querer). Máximo 233 bytes.

## 4. Pendiente

### Iteración 2 — transporte y gating (puntos 6–8 del encargo) — COMPLETA
1. ~~Contrato v1: `command.send_text`~~ implementado (ADR 0027 §3).
2. ~~`system_settings.nexus_mode_enabled` + guard~~ implementado (§5).
3. ~~Migración: `nodes.is_nexus`~~ implementado (§5).
4. ~~Cola persistente + worker con `CommandPacer`~~ implementado (§4).
5. ~~Inspector: separar "Radio / LoRa" (nativo) y "JenTastic-Nexus"~~
   implementado (§8, 2026-09-29): pestaña `nexus` visible solo con flag ON
   y nodo marcado, mismo formulario previsualizar→confirmar→encolar que
   Ajustes pero con destino fijo a este nodo.

### Punto 2 del encargo (parsers)
Por cada formato de `PENDING_FORMATS` (STATS, WATCH STATS, CONFIG,
FIREWALLSTATS, NODES, SECURITY): captura real → parser → test con la captura.
Confirmar también el formato de cabecera de página (¿`P1:` o `P1/3:`?).

### Punto 3 — autorización
- Leer `SECURITY` de cada nodo (necesita el parser de SECURITY) y mostrar el
  bitmask; aviso si `ALLOW_DM` está OFF antes de ofrecer DM, con activación
  confirmada (`SECURITY ALLOW_DM on` + `SAVE`).
- Por defecto todo por el canal de confianza (ya decidido).

### Punto 4 — UI
- Perfil de nodo con la plantilla del §6 del documento (rol, NI, TEL_D/E/P,
  POS, SMART, FIXED, GPS, LOC, LoRa manual SF/BW/CR/Freq) que genere
  SETCONFIG/SETROLE/SETLORA. Necesita el parser de CONFIG para mostrar el
  valor actual.
- Modal de confirmación para `destructive`, indicador "aplicando…" con
  `busy_seconds`, aviso "cambios sin guardar" con `requires_save` y botón SAVE.

### Captura real (2026-09-28) y lo que confirmó

Sesión con los dos nodos reales del usuario por USB (X1 = emisor, T1000-E =
objetivo, firmware `2.7.268.dd79d33`), canal `Nexus` (índice 7, detectado por
nombre, confirmado que NUNCA se salió de él). Herramienta:
`tools/nexus_capture.py`. Guardada en
`backend/tests/fixtures/nexus/captura-20260928-x1-t1000.{md,jsonl}` (datos
reales de la malla del usuario — short names de sus propios nodos; avisar
antes de hacer público el repo si eso importa).

Confirmado y **ya aplicado al código**:
- Las respuestas empiezan por `JT <COMANDO>:` (dato) o `JT: <texto>` (avisos
  del sistema, incl. `JT: Unknown command 'X'`) — tal y como afirmaba el
  prompt v2.8.006. `parse_response` detecta `Unknown command` de forma
  genérica antes de intentar cualquier parser (`kind="unsupported"`).
- **El reensamblado debe concatenar SIN separador**, no con `\n` — una
  página puede cortar a mitad de un ID de nodo (`...!e5f720` + `35:N007:...`
  → `...!af000009:N007:...`). Corregido en `reassembly.py` (antes usaba
  `\n".join(...)`, invención sin datos que resultó ser incorrecta).
- La doble copia real (móvil local + malla) tardó **5.36 s**, más que la
  ventana de deduplicación de 5 s que se había estimado sin datos.
  `DEFAULT_DEDUPE_WINDOW` subido a 8 s.
- `SECURITY` no existe en firmware < 2.8.005 (`JT: Unknown command
  'SECURITY'`) — dato real, no fallo de parser.
- Siete formatos con parser real (`parsers.py`): VERSION, INFO, STATS,
  CONFIG, LORA, DROPS, NODES. `FIREWALLSTATS` tiene captura real pero se
  deja sin parser estructurado a propósito: reutiliza etiquetas (`Port:`,
  `RL Pass:`, `RL Drop:`) para grupos de sub-campos distintos cada vez —
  aplanarlo sin inventar nombres desambiguadores no es seguro con una sola
  captura.
- `NODES` y `CONFIG` (ambos paginados) verificaron el fix de concatenación
  con datos reales, no solo con un test sintético.

## 0.4 Captura real de SETCONFIG/SETROLE/SETLORA (2026-09-28)

Mismos dos nodos, tras reiniciar gw-01 (bloqueaba el puerto USB del T1000
con un descriptor abierto de un escaneo anterior — reiniciado por el
usuario, nunca por mí, confirmado antes de tocar nada). Plan deliberadamente
conservador (acordado con el usuario antes de mandar nada): leer
CONFIG/ROLE/LORA-STATUS como referencia, mandar SETCONFIG/SETROLE/SETLORA
**sin argumentos** (nunca un valor inventado) y releer los tres al final
para confirmar que nada cambió. Fixture:
`backend/tests/fixtures/nexus/captura-20260928-x1-t1000-setconfig.{md,jsonl}`.

- **`SETCONFIG` sin argumentos respondió con su propio mensaje de uso**:
  `JT SETCONFIG: NI|TEL_D|TEL_E|TEL_P|POS|SMART|FIXED|GPS <val> | LOC
  lat,lon` — sintaxis real confirmada: UN campo por comando (nunca varios a
  la vez), `LOC` como forma especial `lat,lon` sin espacio. Aplicado al
  perfil de nodo (ver más abajo).
- **`SETROLE` y `SETLORA` respondieron los dos "JT: Unknown command"** — no
  existen con ese nombre en el firmware probado (2.8.005, build PRIVADA,
  más comandos que la pública) pese a que `SETLORA` estaba catalogado como
  confirmado por el manual. Si ni la build privada lo reconoce, es dudoso
  que exista de verdad — comentado en `catalog.py`, NO eliminado del
  catálogo (un "Unknown command" del firmware es inofensivo, nunca aplica
  nada), pero excluido de la plantilla de perfil de nodo hasta confirmarlo.
  Efecto directo: el encargo original pedía editar Rol y LoRa manual
  (SF/BW/CR/Freq) desde el perfil — NO es posible con lo confirmado hasta
  ahora; el perfil de nodo implementado (§Punto 4) solo cubre los 8 campos
  reales de `SETCONFIG`, Rol se muestra de solo lectura.
- **Sin efectos secundarios**: `CONFIG`/`ROLE`/`LORA-STATUS` releídos al
  final son IDÉNTICOS a la lectura inicial — confirmado que enviar el
  comando sin argumentos no cambió nada, como se esperaba.
- Durante la sesión el stack Docker (postgres/redis/backend/frontend) había
  caído por su cuenta (no por ninguna acción mía) — gw-02 se quedó
  reintentando Redis en silencio hasta relanzar el stack; documentado como
  recordatorio de diagnóstico, no como bug del módulo.

## 0.5 WATCH STATS con entrada real en el watchlist (2026-09-28)

Petición directa del usuario: "añade al watch el otro nodo y después haces
el stats". Secuencia contra el T1000 (con el X1 emisor como objetivo del
watch): `WATCH LIST` (vacío) → `WATCH ADD !af000001` → `WATCH LIST`
(confirma) → `VERSION` (genera tráfico real DEL nodo vigilado, ya que el
propio comando lo manda el X1) → `WATCH STATS` → `WATCH DEL !af000001`
(limpieza) → `WATCH LIST` (confirma vacío otra vez, sin dejar rastro).
Fixture: `backend/tests/fixtures/nexus/captura-20260928-x1-t1000-watch.
{md,jsonl}`.

Respuestas nuevas, confirmadas y reales:
- `WATCH LIST` vacío: `JT: Watchlist empty.`
- `WATCH ADD <hex8>`: `JT: Added <hex8> to watchlist.`
- `WATCH LIST` con entradas: `Watchlist: af000001[N001]` — **sin el
  prefijo `JT:`** de las demás respuestas de este subsistema (inconsistencia
  real del firmware, no un error de captura — ya sale así del nodo).
- `WATCH DEL <hex8>`: `JT: Removed <hex8>.`

**`WATCH STATS` sigue sin devolver datos, incluso con una entrada real en
el watchlist y tráfico real de ese nodo de por medio** (la propia respuesta
a `WATCH ADD` viaja EN el mismo paquete que manda el nodo vigilado) — la
respuesta fue, otra vez, el mensaje de uso genérico
(`ADD|DEL|LIST|CLEAR|RESET|STATS|ALL`). Con dos intentos ya (subsistema
vacío y subsistema con una entrada activa) el patrón deja de parecer "hace
falta más estado" y empieza a parecer que `STATS` no está implementado de
verdad en este firmware pese a aparecer listado como verbo válido — o que
necesita un argumento no documentado (¿`WATCH STATS <hex8>`, por analogía
con `ADD`/`DEL`?, sin probar). Se queda en `PENDING_FORMATS` con esta nota;
no se ha intentado `WATCH STATS !af000001` todavía.

## 0.6 WATCH STATS resuelto: exige el node_id como argumento (2026-09-28)

El propio usuario lo probó en directo en paralelo a la sesión anterior y
avisó: "Hice /nexus watch stats !af000001 y funciona, tras haber hecho
watch add !id" — confirmando la sospecha anotada en §0.5 ("¿necesita un
argumento no documentado, por analogía con ADD/DEL?"). Repetido con
captura formal: `WATCH ADD !af000001` → `VERSION` (tráfico) →
`WATCH STATS !af000001` → `WATCH DEL` (limpieza) → `WATCH LIST` (confirma
vacío). Fixture: `backend/tests/fixtures/nexus/captura-20260928-x1-t1000-
watch-stats.{md,jsonl}`. La sesión de captura coincidió con el propio
usuario probando comandos en directo desde el mismo canal — se ve en la
transcripción cruda (marcador 🔴 en vez de 🟢 en varias respuestas —
significado del color aparte del semáforo de firma, sin confirmar; no
interfirió con la captura, solo añadió ruido extra en el primer bloque).

Con el node_id, `WATCH STATS` responde una tabla paginada real:
`JT Watch Stats:\nTarget: <hex8>\nPkts: N Bytes: N\nRF (Direct Only):\n
Avg:<N>dB SNR:<N> FE:<N>\nSD: <N> SNR:<N> FE:<N>\nMin:<N>dB SNR:<N> FE:<N>
\nMax:<N>dB SNR:<N> FE:<N>\nHops: h0:N h1:N h2:N h3:N h4:N\nRelay:
Last:N Primary:N (N)\nTiming: Min:Ns Max:Ns Age:Ns\nPorts: NI:N POS:N
TEL:N TXT:N ADM:N RT:N OTH:N`. `parse_watch_stats` (parsers.py) lo
estructura completo — `Min:`/`Max:` aparecen dos veces (RF en dB, Timing en
segundos), distinguidos por el sufijo de unidad en el propio patrón, sin
colisión ni invención, cada sección en su grupo anidado (`rf`/`hops`/
`relay`/`timing`/`ports`). Junto con `WATCH LIST`/`ADD`/`DEL` (§0.5), el
subsistema WATCH queda completamente cubierto salvo la sintaxis exacta de
`FSIG SET`/`OFF`, que sigue siendo la única pieza sin confirmar de la
lista original de pendientes.

## 0.7 FSIG SET/OFF confirmado por captura real (2026-09-28)

Última pieza pendiente de la lista original. Secuencia (slot de prueba,
patrón de texto inocuo, restaurado al final): `FSIG` (baseline, S1..S8
OFF) → `FSIG SET 1 TEST` → `FSIG` (verifica) → `FSIG OFF 1` (restaura) →
`FSIG` (confirma vuelta a OFF). Fixture: `backend/tests/fixtures/nexus/
captura-20260928-x1-t1000-fsig-set.{md,jsonl}`.

- `FSIG SET <1-8> <patrón>` confirma con `JT: S<n> set (<encoding>, <N>B).`
  — aquí `(text, 4B)` para el patrón `TEST`. Coincide con lo que el manual
  ya adelantaba (auto-detección hex/base64/texto, máx. 16 bytes), ahora
  con la confirmación real del mensaje de éxito.
- La consulta `FSIG` tras el `SET` muestra el slot activo como
  `S1: TEST (text) (4B)` — patrón tal cual, codificación entre paréntesis,
  tamaño en bytes entre paréntesis. `parse_fsig` (parsers.py) reescrito
  para reconocer este formato (`{"active": true, "pattern", "encoding",
  "bytes"}`), con fallback a `{"active": true, "raw": <texto>}` si algún
  día aparece una codificación no vista (hex/base64 documentados por el
  catálogo, sin captura propia todavía).
- `FSIG OFF <1-8>` confirma con `JT: S<n> cleared.` — la relectura final
  confirma que el slot vuelve a `OFF`, sin dejar rastro.

Con esto se cierra el último punto pendiente de la lista de §0 del
documento — no queda ningún formato sin confirmar salvo `FIREWALLSTATS`
completo (necesita una segunda captura con datos no-cero, ver §0.2 de
`parsers.py`) y la matriz de compatibilidad por versión/hardware, que
nunca fue parte del encargo de esta iteración.

## 0.8 FIREWALLSTATS resuelto del todo, sin necesitar nueva captura (2026-09-29)

Pedido explícito del usuario tras cerrar §0.7 ("hazlo también"). Al
revisar de nuevo la ambigüedad que había dejado `FIREWALLSTATS` sin
parser completo, la conclusión inicial ("hace falta una segunda captura
con valores distintos de cero para desambiguar") resultó estar mal
diagnosticada: la ambigüedad nunca fue de VALORES, fue de ETIQUETAS
repetidas (`Port:` aparece 3 veces, `RL Seen`/`RL Pass`/`RL Drop` 2 veces
cada una, `Trace` 2 veces) — y esa ambigüedad se resuelve por completo sin
ningún dato nuevo, con una regla puramente posicional: en vez de fusionar
todas las líneas en un único diccionario plano (ahí sí colisionarían),
`parse_firewallstats` (parsers.py) genera `extra_sections`, una LISTA
ordenada con una entrada por línea (`label`, `fields`, `raw`) — dos líneas
`Port:` conviven como dos entradas distintas, nunca se pisan, y de hecho
sus conjuntos de campos ni siquiera coinciden entre sí (`NI/PO/TL` vs.
`NB/TR/SF` vs. `AD/TX/KV/AL/WP`), así que tampoco haría falta esta
separación por seguridad extra, pero se mantiene por claridad y para no
depender de que eso siga siendo así en el futuro.

Único caso genuinamente indecidible dentro de una línea: `HOP: 6:0 7:0
PRE: 0 ACKS: 0` — el `6:0`/`7:0` son pares compuestos (un número seguido
de más ":") que no se pueden distinguir de un "valor suelto seguido de
ruido" sin adivinar; se excluyen a propósito de `fields` (quedan solo en
`raw`, dentro de esa misma entrada de `extra_sections`) mientras que
`PRE`/`ACKS`, inequívocos, sí se capturan. Verificado línea por línea a
mano contra la captura real completa (`captura-20260928-x1-t1000.md`,
comando `FIREWALLSTATS`, todos los valores en cero) antes de escribir el
código — los 19 tests nuevos/actualizados de `test_parse_firewallstats`
pasaron a la primera, confirmando el análisis. 521 tests backend+gateway,
ruff limpio. Sin cambios de frontend (FIREWALLSTATS no tiene UI dedicada,
solo aparece como JSON crudo en el historial genérico de operaciones).

## 0.9 Favoritos/ignorados propios de Nexus: sí son "solicitables" (2026-09-28)

El usuario preguntó directamente si había "registro de favoritos e
ignores con Nexus", "¿solicitable?" — la respuesta es SÍ: categoría
NodeDB del catálogo, familia completa `FAVS`/`IGNORED` (consulta) y
`FAV`/`UNFAV`/`IGNORE`/`UNIGNORE` (mutan), sin relación alguna con los
favoritos/ignorados remotos NATIVOS (M4.1/M4.2, AdminMessage — mecanismo
totalmente distinto, lista distinta). Confirmado por captura real (mismo
patrón de siempre: leer estado, mutar, releer, restaurar):
`FAVS` → `IGNORED` → `FAV !af000001` → `FAVS` → `UNFAV !af000001` →
`FAVS`. Fixture: `backend/tests/fixtures/nexus/captura-20260928-x1-t1000-
favs.{md,jsonl}`.

- `FAVS` responde paginado, mismo patrón `!<hex8>:<shortname>` que
  `NODES` pero sin sub-campos — 19 favoritos reales en la malla del
  usuario (incluido un nombre corto con emoji, `N016`, que no confunde el
  regex de extracción).
- `IGNORED` con la lista vacía respondió `JT Ignored:\n` (cero entradas)
  — confirmado, no un fallo de parser.
- `FAV`/`UNFAV` confirman los DOS con el mismo texto genérico
  `JT: Updated node <hex8> (<shortname>)` — no distinguen en el mensaje
  si añadió o quitó, hay que fiarse de qué comando se mandó (mismo techo
  ya documentado en ADR 0019 para el equivalente nativo: sin GET de
  verificación posible).
- `IGNORE`/`UNIGNORE` NO tienen parser todavía — solo se probó `FAV`/
  `UNFAV` contra hardware; asumir que comparten formato sin verlo sería
  inventar. Siguen disponibles sin atajo dedicado, vía el catálogo
  completo/formulario genérico.

UI nueva (`NodeNexusFavorites`, `NodeNexusPanel.tsx`): botones "Leer
favoritos"/"Leer ignorados", lista de favoritos con "Quitar" por fila +
campo para añadir uno nuevo (precarga `FAV`/`UNFAV`, nunca envía sola),
lista de ignorados de solo lectura. 531 tests backend+gateway, ruff/tsc/
build limpios.

## 0.10 Zero Hop (ZH) destacado igual que favoritos/ignorados (2026-09-28)

Pedido explícito del usuario: "con JT/Nexus activado también quiero
destacar como los favoritos e ignores, el zero hop ZH". Confirmado real
(mismo patrón leer→mutar→releer→restaurar). **Bug propio encontrado y
corregido a mitad de la prueba**: la primera captura mandó
`ZH ADD !af000001` con el id SIN truncar (`tools/nexus_capture.py` no pasa
por `build_command`, manda el texto literal) — el firmware respondió
`ZH ID 0x00 ADDED` (dato real pero sin sentido para lo que se quería
probar, ya que la pasarela SÍ aplica `zero_hop_suffix` antes de mandar).
Repetido con el argumento YA truncado (`ZH ADD 90`, los 2 últimos hex del
id real del nodo — anonimizado como `!af000001` en esta documentación, el
"90" es el valor real observado) — el usuario confirmó en paralelo, sin
que se lo preguntara directamente: "el ZH es sólo con los dos últimos
dígitos del ID".
Fixture: `backend/tests/fixtures/nexus/captura-20260928-x1-t1000-zh.
{md,jsonl}`.

- `ZH LIST` vacío: `JT: ZH List is EMPTY`.
- `ZH LIST` con una entrada: `ZH List:\n[90] N001,N043\n` — SIN el
  prefijo `JT:` (misma inconsistencia ya vista en `WATCH LIST`/`FAVS`).
  El segundo campo tras la coma (`N043` aquí) no tiene significado
  confirmado, se devuelve tal cual bajo `extra` sin interpretarlo.
- `ZH ADD 90` confirma con `JT: ZH ID 0x90 ADDED`; `ZH DEL 90` con
  `JT: ZH ID 0x90 REMOVED`.
- **`build_command` ya trunca automáticamente** (`addressing.
  zero_hop_suffix`, confirmado antes de esta captura) — el panel nuevo
  (`NodeNexusZeroHop`) deja escribir un `!id` completo o ya solo 2 hex,
  el backend hace la conversión real, sin duplicar esa lógica en el
  cliente.

UI nueva junto a Favoritos/Ignorados en la pestaña Nexus del Inspector:
leer lista, quitar con un clic, añadir con un campo. 535 tests
backend+gateway, ruff/tsc/build limpios.

### Sigue pendiente (necesita otra captura o el manual v2.8.006)
- Tiempo de reinicio de NAME/OWNER/REVERT.
- Qué cambios persisten solos (el documento menciona `BD` sin definirlo).
- Sintaxis exacta de `FSIG` por slot (`SET <1-8> <patrón>`/`OFF <1-8>`) —
  solo se probó la consulta sin argumentos (§0.3).
- Si `PRALLOW`/`PRBLOCK` desaparecen del todo en v2.8.006 o coexisten con
  `PRWHITELIST`/`PRBLACKLIST` (de momento se mantienen ambos pares).
- Significado real de los dos valores numéricos y las letras (`K+`/`KV`) de
  cada entrada de `NODES`, y de `HM`/`RM` en `CONFIG` — se devuelven en el
  parser sin interpretar.
- Si `RL` a secas es RSSILOG o RATELIMIT.
- `FIREWALLSTATS` estructurado (ver arriba, necesita más de una captura para
  desambiguar las secciones repetidas).
- `WATCH STATS` real con entradas en watch (ver §0.3: la única captura
  disponible devolvió el texto de ayuda, sin nada que estructurar).
- **Confirmado con el usuario (2026-09-28): los dos nodos de prueba corren
  la build PRIVADA/táctica, no la pública que documenta el manual** (ver
  §0.3). **Decisión explícita del usuario, cerrada**: MeshSentinel trabaja
  SIEMPRE sobre la build pública, aunque los nodos de prueba (y quizá la
  malla real) tengan de hecho la privada con más comandos — el catálogo
  sigue excluyendo `BURNER`/`ROLEMASK`/`SETMULTIROLE`/`ADDURL`/
  `USETCHNAME` (§0.0) tal cual, sin probarlos contra hardware aunque
  respondieran. Si un parser de un comando PÚBLICO recibe campos extra de
  una build privada (como pasó con `SECURITY`, §0.3), se siguen exponiendo
  tal cual llegan (no se filtran) porque el parser no sabe ni le
  corresponde saber qué build responde — pero no se amplía el catálogo de
  comandos para ir a buscarlos.

## 0.3 Segunda captura real — SECURITY/SETTINGS/FSIG/WATCH STATS/LORA-STATUS (2026-09-28)

Mismos dos nodos (X1 emisor, T1000-E objetivo), ya ambos en firmware
2.8.005, por el canal Nexus (índice 7), con `tools/nexus_capture.py
--commands "SECURITY" "SETTINGS" "FSIG" "WATCH STATS" "LORA-STATUS"`. gw-02
(gateway nativo USB) parado durante la captura y relanzado después con los
mismos parámetros exactos (`GATEWAY_ID=gw-02 MESHTASTIC_USB_DEVICE=
/dev/cu.usbmodem101`). Guardada en
`backend/tests/fixtures/nexus/captura-20260928-x1-t1000-security-settings-fsig.{md,jsonl}`.

Cuatro parsers nuevos con datos reales (`parsers.py`): **SECURITY**,
**SETTINGS**, **FSIG**, **LORA-STATUS**. Ya no quedan en `PENDING_FORMATS`.

- **No es un error del manual, es la build**: §0.0 había dado por confirmado
  que `AUTO_FAV_NEXUS`/`AUTO_FAV_TRUSTED`/`BYPASS_RP` estaban AUSENTES de la
  build PÚBLICA de `SECURITY` (solo 3 bits documentados: `REQ_SIG`/
  `ALLOW_DM`/`SILENT_LOG`) — eso sigue siendo correcto para la build
  pública. La respuesta real trae 6 campos (`REQ_SIG`, `ALLOW_DM`,
  `SILENT`, `FAV_NX`, `FAV_TR`, `BYPASS_RP:off (28/256)`) porque **los dos
  nodos de prueba del usuario corren la build PRIVADA/táctica**, no la
  pública que documenta el manual (confirmado por el usuario tras ver este
  hallazgo) — la misma familia de extensiones "private/tactical" ya
  excluida del catálogo por nombre de comando (`BURNER`/`ROLEMASK`/
  `SETMULTIROLE`/`ADDURL`/`USETCHNAME`, §0.0) existe también como CAMPOS
  EXTRA dentro de respuestas de comandos que sí son públicos (`SECURITY`
  en este caso): `FAV_NX`≈`AUTO_FAV_NEXUS`, `FAV_TR`≈`AUTO_FAV_TRUSTED`. El
  parser (`parse_security`) devuelve los 6 tal cual los da el firmware, sin
  filtrar ni asumir cuáles son "públicos" — un nodo con build pública de
  verdad simplemente no mandaría los 3 campos privados, y el parser
  seguiría funcionando igual (regex por línea, no por conteo fijo de
  campos). `BYPASS_RP` trae además un contador entre paréntesis (`28/256`)
  sin decorar, capturado como `bypass_rp_extra`, significado sin confirmar.
  **Pendiente a valorar con el usuario**: si sus nodos reales son todos de
  build privada, los comandos excluidos del catálogo por "ausentes de la
  build pública" (`BURNER`/`ROLEMASK`/`SETMULTIROLE`/`ADDURL`/
  `USETCHNAME`) podrían SÍ existir en su malla — la exclusión actual se
  basa solo en lo que dice el manual del build público, nunca se probaron
  esos comandos contra hardware real.
- `SETTINGS` responde con formato tokenizado libre (`Clave:valor Clave:
  valor...`), sin unidades explícitas salvo `BD:5s` — `parse_settings`
  reusa el mismo criterio genérico que `STATS` (regex de tokens, sin
  normalizar valores hex/fracciones).
- `FSIG` sin argumentos (consulta, no `SET`/`OFF`) responde en DOS mensajes
  separados: un aviso suelto no paginado (`🟢 JT: Paging signatures...`,
  cae a texto crudo — no tiene cabecera `JT FSIG:`) y luego una respuesta
  de UNA página (`P1: JT Signatures:\n...`) cuya cabecera real, tras
  quitar `reassembly.py` el prefijo `P1: `, es `JT Signatures:` — no
  `JT FSIG:` como el resto de comandos. `parse_fsig` usa esa cabecera real.
  Sintaxis de `SET`/`OFF` por slot sigue sin probar (fuera de alcance de
  esta captura, solo lectura).
- `WATCH STATS` (con el subsistema WATCH vacío, sin entradas añadidas)
  respondió con el texto de ayuda genérico del comando
  (`ADD|DEL|LIST|CLEAR|RESET|STATS|ALL`), no una tabla de estadísticas —
  se queda en `PENDING_FORMATS`, nada que estructurar con esta captura.
- `LORA-STATUS` (`LRS`) confirmado con formato PROPIO, distinto de `LORA`:
  trae `Freq`/`BW`/`SF`/`CR`/`Pre` (preámbulo en símbolos y ms)/`Slot`/
  `CW`/`SW` (sync word)/`ChipPwr`/`Speed` — ningún campo compartido con el
  parser de `LORA` salvo `SF`/`CR`/`Freq`, registrados por separado.

Con esta captura quedan resueltos todos los formatos de la lista "sigue
pendiente" salvo: sintaxis de `SET`/`OFF` de `FSIG`, `WATCH STATS` con
datos reales, si `PRALLOW`/`PRBLOCK` desaparecen, `FIREWALLSTATS`
estructurado, y el significado de los campos sin etiquetar de `NODES`/
`CONFIG`.

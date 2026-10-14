# Estudio: firmware JenTastic-Nexus público vs. nuestro módulo Nexus

> Fecha: 2026-10-13. Sin código tocado: es un estudio. Las correcciones propuestas
> están priorizadas al final (§5) y esperan aprobación.

## 0. Alcance y método

- Repo: `github.com/derpyspike/jentastic`, rama por defecto, commit `b8c53ee`
  (firmware **2.8.103** = upstream 2.8.1 + build JT 03; un único commit squashed,
  sin historial útil). Licencia AGPLv3 para el módulo Nexus.
- Leído entero: `README.md`, `docs/manual.md`, `docs/nexus-commands.md` (815 líneas),
  `NEXUS_KEYS.md`, `SECURITY.md`, `build-*.sh`, y el **código fuente**
  (`src/modules/NexusModule.cpp` 5852 líneas, `NexusCommands.cpp` 9063 líneas).
- Método: (1) diff mecánico del catálogo (`catalog.py`, 186 comandos + 66 alias)
  contra los 270 nombres de comando que el despachador del firmware compara
  (`strcasecmp(cmd, "...")`); (2) los formatos de respuesta del fuente
  (`snprintf`) pasados por nuestros parsers; (3) lectura de las rutas críticas
  (despacho, direccionamiento, paginación, firma, seguridad).
- **El código fuente prevalece sobre `docs/nexus-commands.md`** cuando discrepan
  (la doc tiene erratas propias, p. ej. dice que `SETROLE`/`SETLORA` existen pero
  no avisa de que exigen argumento). Y sobre el PDF 2.8.006 en todo lo anterior.

Hallazgo de contexto importante: el árbol público se **genera** con
`bin/nexus_strip_tactical_to_public.py` (`NexusCommands.cpp:28-34`, `:472`):
lo táctico vive en `handlePrivateCommand()` bajo `#ifdef NEXUS_PRIVATE_BUILD` y
**no está en el repo público**. Eso zanja qué es "build pública".

## 1. Resumen ejecutivo

| # | Hallazgo | Tipo | Gravedad |
|---|----------|------|----------|
| H1 | `INVALIDS <REGLA> [ON\|OFF]` **no existe**: la sintaxis real es `INVALID <R>` / `UNINVALID <R>` | Bug nuestro | Alta |
| H2 | `-mac` compara **2 bytes (4 hex)**, no 3 (6 hex): nuestro destino MAC nunca acierta | Bug nuestro | Alta |
| H3 | Marcador de firma de 4 estados (🔒🟢🟠🔴); solo reconocemos 🟢🔴 | Bug latente | Alta |
| H4 | "SETROLE/SETLORA no existen" era un **falso negativo** de nuestra prueba (exigen argumento) | Conclusión errónea | Alta (desbloquea funcionalidad) |
| H5 | Listas paginadas se truncan **en silencio** a 2 KB; las leemos como completas | Integridad de datos | Media-Alta |
| H6 | `SECURITY` gana la línea `FAV_XT` (7.º bit) que no parseamos; los rechazos `JT SECURITY: rejected` no se interpretan | Parser | Media |
| H7 | 11 comandos del catálogo **no existen** en el firmware público (privados) | Catálogo | Media |
| H8 | 14+ comandos/alias públicos **faltan** en el catálogo (TRACE, METRICS, LCS, SENDSTATUS, STATUSPS, ADDURL, AIRTAG…) | Catálogo | Baja-Media |
| H9 | Profundidad de `R` anidado: el firmware admite 3, nosotros 2 | Divergencia benigna | Baja |
| H10 | Colisión de nombre corto en `-node`: el comando llega a TODOS los nodos con ese nombre | Riesgo operativo | Media |
| O1–O6 | Oportunidades nuevas (vecinos reales, TRACE remoto, NODE_STATUS_APP…) | Mejora | — |

## 2. Hallazgos que exigen cambio (bugs y correcciones)

### H1 — `INVALIDS`: sintaxis equivocada (regresión de una "corrección" nuestra)

`NexusCommands.cpp:5548-5558`: el firmware reconoce
`INVALIDS` / `INV` / `INVALID` (bare = consulta), `INVALID <REGLA>` / `INV <REGLA>`
(activa) y `UNINVALID <REGLA>` / `UNINV <REGLA>` (desactiva). **No hay `[ON|OFF]`**:
`INV NULL OFF` cae al `else` y solo repite el estado.

Nuestro catálogo (`catalog.py:169-171`, decisión del manual 2.8.006) lo modeló como
un único comando `INVALIDS <RULE> [ON|OFF]`. Comprobado: nuestro builder emite
`/nexus INVALIDS NULL ON`, que **no coincide con ninguna rama** (`INVALIDS` es
comparación exacta y el prefijo `INVALID ` tiene un espacio en la posición 8) →
`JT: Unknown command`. Cualquier intento de configurar reglas de validez falla.

**Cambio**: restaurar `INVALID`, `UNINVALID` (y alias `INV`, `UNINV`) como
mutaciones separadas; `INVALIDS` solo consulta. Actualizar el comentario de
`catalog.py:24` que afirma lo contrario.

### H2 — `-mac`: 2 bytes, no 3

`NexusModule.cpp:4686-4698`: `ourMacSuffix = (mac[4] << 8) | mac[5]` y se compara
con `strtoul(arg, 16)`. Es decir, **4 dígitos hex**. La doc lo dice explícito
("A full 6-byte MAC will not match"). Nuestro `addressing.py:20-22` exige y emite
**6 hex** ("`<mac6>`, 3 bytes, no 4 como se había dejado sin confirmar").
Un valor de 6 hex (`a1b2c3`) nunca iguala un sufijo de 16 bits → silencio total.
El manual PDF se equivocaba (o describía otra build).

**Cambio**: `Mac` = 4 hex; actualizar validación, la UI (`NexusOperationsPanel.tsx:49`
"MAC (-mac, 6 hex)" y el placeholder), tests y la nota de `pacing.py`.
Ojo: 4 hex = 65 536 valores → **colisiones plausibles** en una malla de miles de
nodos; el aviso de H10 aplica también aquí.

### H3 — El marcador delante de la respuesta tiene 4 estados, no 2

Cola del despachador (`NexusCommands.cpp:9010-9024`, y la copia de la ruta
privada `:512-523`): todas las respuestas llevan prefijo según **cómo llegó el
comando**:

| Marcador | Significado |
|----------|-------------|
| 🔒 | firmado, verificado **y firmante en la lista de confianza** (admin/secondary/master) |
| 🟢 | firmado y verificado, firmante **no** de confianza |
| 🟠 | firma presente pero **falla** la verificación |
| 🔴 | sin firma |

Nosotros asumimos "semáforo de firma válida" con solo 🟢/🔴:
`reassembly.py:36-37` (`MARKER`, `PAGING_TRAILER`), `parsers.py:102`
(`_SIGNATURE_RE`) e `interpret.py:48`. `_first_line` sí tolera cualquier token,
pero `looks_like_nexus_signature` (detección pasiva), el filtro de marcador del
reensamblado y la interpretación **descartan o no reconocen 🔒/🟠**.

Consecuencia concreta: en cuanto la pasarela firme sus comandos (2.8 firma los
mensajes de canal) **y** su clave esté en `SKEY`/admin del destino, todas las
respuestas llegarán con 🔒 y la detección pasiva/paginación degradarán. Hoy no
se ve porque los nodos de prueba tienen `REQ_SIG` off y las respuestas son 🔴/🟢.

**Cambio**: conjunto `🔒🟢🟠🔴`; y **aprovecharlo**: guardar el marcador como
`signature_state` de cada respuesta (es la única señal gratuita de "¿mi
pasarela está autorizada en ese nodo?"). Ver O5.

### H4 — `SETROLE` y `SETLORA` sí existen (corrige una nota nuestra)

En la sesión de campo del 2026-09-29 concluimos "`SETROLE`/`SETLORA` NO EXISTEN
en el firmware real (`JT: Unknown command`)" y recortamos el perfil de nodo.
El fuente lo desmiente: `NexusCommands.cpp:4095` (`strncasecmp(cmd, "SETROLE ", 8)`)
y `:5252` (`"SETLORA "`). **Exigen un argumento**: la sonda "sin argumentos" cayó
al `else` final ("Unknown command") por construcción. Fue un falso negativo
nuestro; el firmware nunca los quitó.

- `SETROLE <role>`: `CLIENT SENSOR ROUTER RTR_CLIENT BASE/CLIENT_BASE MUTE HIDDEN
  LOST TAK TAK_TRACKER` o dígito 0-13. Aplica con `handleSetConfig` (inmediato).
- `SETLORA <sf> <bw> <cr> <freq>`: SF 5-12, CR 5-8, BW 31/62/125/250/500 (o
  200/400/800/1600 en 2.4 GHz), **freq 863-873 o 2400-2500 MHz**; aplica "LIVE
  en 5 s" (`pendingLoRaConfig`).
- `PRESET`/`SETPRESET <p>` también (tabla de presets EU_868 en la doc).

**Cambio**: reabrir en el perfil de nodo (Rol y LoRa manual/preset) con
confirmación; `SETLORA`/`PRESET` ya figuran como destructivos con `busy_seconds`.
Corregir la entrada de CLAUDE.md y `docs/design/nexus-control.md`.
Lección: la existencia de un comando se comprueba con argumento ficticio **o
contra el fuente**, nunca bare.

### H5 — Las listas paginadas se truncan en silencio a 2 KB

`NexusModule.h:925`: `char paging_buf[2048]`; `NexusModule.cpp:5402-5407`
(`appendPaging`): si la entrada no cabe **se descarta sin marcador**. No hay
cabecera de total ni "…". `FAVS`, `IGNORED`, `NODES`, `NEIGHBORS`, `ZH LIST`,
`NIGN`, `INFRA`, etc. salen incompletas cuando exceden ~2 KB (≈55-60 filas
`!xxxxxxxx:ABCD `).

Impacto: `nexus_node_flags` (migración 0029) **sustituye** la lista conocida con
cada lectura `FAVS`/`IGNORED` (ver CLAUDE.md, "Consola Nexus"). Un router con
80 favoritos → lectura truncada → **borramos de nuestra lista** los que no
cupieron, y la UI muestra una lista "completa" falsa. Con `NODES` el efecto es
el mismo sobre cualquier uso estadístico.

**Cambio**: marcar la lectura como *posiblemente incompleta* cuando el texto
reensamblado se acerque a 2048 bytes (umbral ≈ 1900) y en ese caso **fusionar**
(no sustituir) o avisar en la UI; documentar en la consola que `NODES` no es un
volcado de la NodeDB.

### H6 — `SECURITY`: `FAV_XT` y rechazos

- `NexusCommands.cpp:4477`: la salida real incluye `FAV_XT:<st> ch<n>` (7.º bit,
  `AUTO_FAV_EXTRA`, canal en los bits 7-9). Nuestra regex de línea
  (`parsers.py:392`) no admite el sufijo ` ch0` → la línea **se descarta sin
  error** (comprobado: el dict resultante no trae `fav_xt`).
- Los rechazos `JT SECURITY: rejected — <motivo>` (`NexusModule.cpp:2412, 2504`;
  motivos: `signature required (REQ_SIG)`, `DM not authorized (ALLOW_DM=OFF)`,
  `replay detected`…) no tienen interpretación: hoy quedan como texto crudo.
  Con `SILENT_LOG` ON el nodo **no responde** y nosotros lo contamos como "sin
  respuesta", indistinguible de un nodo caído o fuera de alcance.

**Cambio**: parser tolerante (`FAV_XT`, `ch<n>`), interpretación de rechazos
("este nodo exige firma: añade la clave de la pasarela con SKEY"), y una pista
en la UI de "sin respuesta" cuando el destino tiene `SILENT`/`REQ_SIG` conocidos.

### H7 — 11 comandos de nuestro catálogo no están en el firmware público

`FAKENODE`, `FNH`, `FNM`, `FAKEPOS`, `FAKERANDPOS`, `FTEXT`, `FTEXTM`, `FTEXTH`,
`INJECT`, `RELAYSPOOF`, `REVERT` (`BSAVE`/`BLOAD` sí existen). Cero coincidencias en el fuente: son del lado
privado/táctico y el build público devuelve `JT: Unknown command`.
Decisión del usuario ya registrada: MeshSentinel trabaja **siempre sobre la
build pública**. Además son herramientas de suplantación (identidad falsa,
paquetes crudos) sin caso de uso en un NOC.

**Cambio recomendado**: moverlos a `EXCLUDED` (o a una categoría `private`
oculta por defecto y no enviable). Efecto colateral bueno: desaparecen del
explorador de catálogo y de las plantillas.

### H8 — Comandos públicos que no están en el catálogo

Presentes en el fuente (algunos también en la doc), ausentes de `catalog.py`:

- **Comandos reales**: `TRACE`/`TR <target>` (traceroute desde el nodo remoto),
  `METRICS <node>`, `LORACHIPSTATS`/`LCS`, `SENDSTATUS <txt>`, `STATUSPS [N]`,
  `CHECKSIG`, `NODECRC <b64>`, `FULLCONFIGDUMP` alias `FCD`, `OKTOMQTT`
  alias `OKMQTT`/`OMQ`, `DM-FORWARD` forma `DMFORWARD`, `IGNORMQTT` (forma
  primaria de la doc; nosotros solo `IGNOREMQTT`), `REBROADCAST` bare.
- **Variantes sin protección de canal de confianza**: `USETCHNAME`, `USETCHPSK`,
  `UDELCH` (la doc las cita; nosotros excluimos `USETCHNAME` por el manual).
- **Excluidos por el PDF 2.8.006 pero PRESENTES en el fuente público 2.8.103**:
  `ADDURL <url>` (añade el nodo del enlace compartido a la NodeDB —
  `NexusCommands.cpp:2960`) y `AIRTAG` (baliza OpenHaystack, `:8328`). Sin
  coincidencia en el fuente: `BURNER`, `ROLEMASK`, `SETMULTIROLE` → siguen
  excluidos correctamente.
- **Alias que nos faltan**: `SETTXPOWER`, `SMN`/`SN`/`SENDMYINFO`, `MC`/`MR`,
  `MSF`, `CHANNELS`/`CHHASHES`, `RLS`, `OTAINFO`, `LCS`.
- **Alias inventados** (sin efecto, porque `resolve()` los canonicaliza antes de
  enviar): `CA`, `BT`, `FP`, `FRP`, `?`, `IGNORE-DUPERELAY`. La doc dice
  expresamente "No `CA` alias", "No `BT` alias", "No `?` alias". Inofensivos
  hoy; conviene limpiarlos para que el explorador no los ofrezca como válidos.

**Cambio**: añadir lo público; decidir `USET*`/`UDELCH`/`ADDURL`/`AIRTAG` con
criterio de riesgo (los tres primeros eluden protecciones → `destructive`,
`broadcast_forbidden`; `AIRTAG` sin caso de uso → mantener excluido).

### H9 — Profundidad de `R` anidado

`NexusCommands.cpp:206,636`: máximo **3** (`R CH a R DM b <leaf>` válido), no 2
como en nuestro `builder.py:43` ("§B1 prompt v2.8.006"). Divergencia
conservadora y benigna; subir a 3 solo si surge necesidad. Detalle útil: un
`R` **se salta el límite de difusión de 5 s** (`last_cmd_time = 0`), no relevante
para nosotros salvo para no usarlo como atajo del pacer.

### H10 — `-node` y colisiones de nombre corto

`NexusModule.cpp:4668-4680`: coincidencia exacta (case-insensitive) con el
`short_name` propio, sin comprobar unicidad. En una malla de >1000 nodos hay
nombres cortos repetidos (4 caracteres): el comando se ejecuta en **todos**
los homónimos. Para mutaciones es peligroso. Nosotros conocemos la flota:

**Cambio**: en `preview` y en el formulario del Inspector, avisar si hay >1
nodo conocido con ese `short_name` (o ese sufijo MAC, H2) y, para comandos
destructivos, bloquear o exigir confirmación reforzada.

## 3. Lo que ya estaba bien (verificado contra el fuente)

- Prefijos y alias de raíz: `/nexus`, `/jt`, `/jent`, `/jentastic` (+`-local`,
  `-device`, `-node`, `-mac`, `-group`) — `NexusModule.cpp:1949, 4643`.
- `-device` exige `!hex8` (compara contra `owner.id`); el fallo de campo
  original tiene la causa que dio el usuario (el id cambió al reflashear) —
  no es un defecto del firmware ni nuestro.
- Cooldown de difusión de 5 s solo para difusión (`NexusCommands.cpp:668-675`);
  dirigidos lo saltan; **silencioso** (sin respuesta) — coincide con `pacing.py`.
- `NAME`/`OWNER` bloqueados en difusión (`:684-688`) — coincide con el builder.
- Paginación: cabecera `P<n>: `, 2 s entre partes, cuerpo ≤180 B
  (`NexusModule.cpp:2889-2910`) — coincide con `reassembly.py`. NETSCAN/
  CLIENTSCAN envían partes **sin** `P#` (CSV con cabecera solo en la 1.ª).
- Parsers `INFO`, `VERSION`, `STATS`, `CONFIG`, `LORA`, `LORA-STATUS`,
  `SETTINGS`, `UPTIME`: formatos idénticos al `snprintf` del 2.8.103
  (probados con cadenas del fuente). `DROPS` devuelve la lista cruda; ojo, las
  **etiquetas de salida de `DROPS` difieren de los alias de entrada de `DROP`**
  (`TD`=traceroute directo en la salida, `TELE_DEVICE`=`TD` en la entrada;
  `RTR`/`LTR`/`PV`/`TDR`/`TDL`) — no traducirlas con el catálogo de entrada.
- Límites: respuesta ≤200 B (`NEXUS_MAX_REPLY`); nuestro límite de 200
  caracteres de comando es correcto.
- Versionado: `2.8.103` = 2.8.**1** + JT **03**; `2.8.005` = 2.8.**0** + JT 05.
  No hay en nuestro código comparaciones numéricas de versión sobre Nexus
  (verificado), pero cualquier regla futura de "firmware obsoleto" debe
  comparar (upstream, build JT) y no la cadena entera.

## 4. Oportunidades que abre el firmware público

- **O1 — Topología real sin NeighborInfo.** `NEIGHBORS`/`DIRECT` (0 saltos con
  SNR), `INFRA`, `RELAYS`, `HOPSTATS` y `NETSCAN` dan vecindad real por
  consulta. Nuestro `node_neighbors` está vacío en la malla real (nadie emite
  NeighborInfo): un sondeo Nexus **acotado y espaciado** a nodos JT marcados
  alimentaría la capa «Malla real» y las reglas de grafo hoy inertes
  (`asymmetric_link`, `router_cluster`, `router_moving`). Hace falta captura
  real de los formatos (CSV de `NETSCAN`, `NEIGHBORS`) antes de parsear.
- **O2 — `TRACE <target>`**: traceroute *desde un nodo remoto*. Complementa el
  `traceroute.run` desde la pasarela y el barrido activo de roadmap §2 con
  presupuesto de aire. Salida: `JT TRACE (<s>s):\n<ruta>\n[Last: <rssi>dBm, <fe>Hz]`
  (`NexusCommands.cpp:398`), asíncrona; también hace falta captura.
- **O3 — `NODE_STATUS_APP` (portnum 36)**: lo que emiten `SENDSTATUS`/`STATUSPS`
  no pasa por nuestro decoder (cero coincidencias). Si la malla JT lo usa,
  hoy es tráfico invisible en el Registro.
- **O4 — `NODES28` / `SEARCHKEY` / `NODECRC`**: `NODES28` distingue nodos con
  protocolo 2.8 (P) y firmantes XEdDSA (V); `SEARCHKEY` busca por clave
  exacta; `NODECRC` calcula el node_num 2.8 = crc32(clave) — es **exactamente**
  la misma fórmula que ya verificamos para `identity` (ADR 0034). Útil como
  contraste cruzado de la fusión de identidades y de `key_security`.
- **O5 — Estado de autorización de la pasarela** (H3): el marcador 🔒/🟢/🟠/🔴
  de cada respuesta + `SECURITY` + `SKEY` permiten un panel "¿está esta
  pasarela autorizada en este nodo? ¿exige firma?". Y plantea una decisión de
  producto: **endurecer con `REQ_SIG` ON** en los nodos JT y registrar la clave
  de cada pasarela como `SKEY` (revocable), en vez de canal abierto.
- **O6 — `GOODPRACTICES`** (NI/POS 72 h, SmartPos OFF, telemetría ≥24 h): ya en
  el catálogo; encaja como perfil/"plantilla de buenas prácticas" de un clic
  con previsualización, dado que es la política de la comunidad española.

## 5. Seguridad y operación (notas, no cambios de código)

- `NEXUS_KEYS.md` publica las **claves públicas** de cinco master keys del
  autor (Eevee, Mew, Uxie, Bloom, Fennekin). Son identidades, no secretos, y
  las builds públicas **no** llevan claves maestras (`docs/manual.md` §6). Para
  nosotros: ninguna acción; sí advertir al usuario si sus nodos corren una
  build con esas claves baked (confían en el autor de forma irrevocable).
- `AUTO_FAV_NEXUS` favorita a **cualquiera** que hable en el canal Nexus y
  `REQ_SIG` está OFF por defecto: el canal es "abierto" salvo configuración.
  Nuestra detección pasiva sugiere nodos JT por el contenido; combinada con
  `AUTO_FAV_*` deja un rastro visible en `FAVS` (no es un problema, pero explica
  favoritos que nadie añadió).
- Autodetección de canal (`gateway/.../meshtastic_stream.py:816`): `("nexus",
  "jent")`. El firmware confía en `Nexus`/`Nexus2` (o los nombres de compilación
  y los 2 slots `TRUSTED`, `NexusCommands.cpp:3569-3724`). `Nexus2` solo y
  `Jenny*` no se detectan por nombre. Hay override por nombre; falta
  exponerlo/leerlo con `TRUSTED`.
- `BD SET <1..300>` puede retrasar respuestas hasta 300 s
  (`broadcast_delay_max_s`); nuestra ventana por defecto es 30 s
  (`nexus_settings.py:123`). Un nodo con `BD` alto parecerá "sin respuesta".

## 6. Plan propuesto (por prioridad)

**Paquete A — correcciones (bajo riesgo, alto valor, ~1 sesión, sin migración):**
1. H1 `INVALID`/`UNINVALID` + test que emita la forma correcta.
2. H2 `-mac` a 4 hex (backend, UI, tests).
3. H3 marcadores 🔒🟢🟠🔴 en `reassembly`/`parsers`/`interpret` y persistir
   `signature_state` (campo aditivo en `response_data`, sin migración).
4. H6 parser `FAV_XT` + interpretación de rechazos de seguridad.
5. H5 detección de lista posiblemente truncada y no-sustitución.
6. H7/H8 catálogo: mover privados a excluidos, añadir los 14+ públicos y
   limpiar alias inventados; corregir CLAUDE.md y `nexus-control.md` (H4).
7. H10 aviso de homónimos en preview.

**Paquete B — capacidad nueva (necesita capturas reales, hardware):**
8. H4: reabrir Rol/LoRa/preset en el perfil de nodo.
9. O1/O2: capturar `NEIGHBORS`, `INFRA`, `NETSCAN`, `TRACE`, `NODES28`,
   `HOPSTATS`, `METRICS`, `LCS` con `tools/nexus_capture.py` (siempre canal
   Nexus, con los dos nodos del usuario) y entonces escribir parsers.
10. O3: decodificar `NODE_STATUS_APP` en el gateway (cambio de contrato
    aditivo, ADR).

**Decisiones del usuario necesarias:**
- ¿Subir `R` anidado a 3 (H9) o dejarlo en 2?
- ¿Incluir `USETCHNAME`/`USETCHPSK`/`UDELCH`/`ADDURL` como destructivos, o
  mantener la política "solo build pública sin eludir protecciones"?
- ¿Endurecer con `REQ_SIG`+`SKEY` (O5) o mantener canal abierto?
- ¿Sondeo periódico de vecindad Nexus (O1)? Consume aire compartido; requiere
  presupuesto y, según ADR 0027, nunca automático por defecto.

## 7. Resultados en hardware (2026-10-14)

Dos T1000 por USB (X1 `emyX` `!e2cb7890` → T1000 `📟` `!215baaee`), canal `Nexus`
(idx 7), batería `tools/nexus_validate_public.py`. Informe final:
`tools/captures/validate-20261014-103211/report.md` (ambos nodos en **2.8.101.08c204f**;
20 PASS, 17 INFO, 2 FAIL; estado inicial = final en las 7 fotos).

**Hallazgo nuevo — incompatibilidad de firma 2.8.0 ↔ 2.8.1.** Con el X1 en 2.8.005 y el
T1000 en 2.8.101 los nodos dejaron de oírse (36/39 pruebas sin respuesta, ni siquiera un
`/nexus-local`). Causa: el commit upstream `9590660` (#11422, "Sign the whole Data
envelope") cambió el buffer firmado y su mensaje dice que no es compatible con
2.8.0-alpha; `checkXeddsaReceivePolicy` (`Router.cpp:771`) **tira** el paquete cuando la
firma no verifica contra una clave autoritativa, sin depender de `strict`/`compatible`.
Tras actualizar el X1 a 2.8.101 se oyen. Consecuencia: en una malla mixta 2.8.0/2.8.1, el
tráfico **firmado** entre ambos grupos se pierde en las dos direcciones; la matriz de
compatibilidad por versión es requisito, no mejora.

| Hipótesis | Veredicto en hardware | Notas |
|---|---|---|
| H1 `INVALID`/`UNINVALID` | **Confirmada** (2.8.005 y 2.8.101) | `INVALIDS NULL ON` → "Unknown command"; `INV`/`UNINV` también valen |
| H2 `-mac` 4 hex | **Confirmada** | 4 hex responde, 6 hex silencio |
| H3 marcador | Confirmada | Siempre 🟢 (no de confianza); 🔒/🟠 pendientes de la fase `security` |
| H4 `SETROLE`/`SETLORA` | **Confirmada** | bare = "Unknown command"; con arg inválido devuelven su mensaje de validación |
| H5 truncado 2 KB | **Confirmada** | `NODES`: 89 filas de 109 nodos, 2057 B, sin aviso |
| H6 `FAV_XT` | Confirmada en 2.8.101 | 7 líneas (`FAV_XT:off ch0`); 2.8.005 emite 6 |
| H9 `R` anidado | **Doc acertada** | solo 1 nivel; el 2.º `R` queda como texto → "Unknown command" |
| H8 `LCS`, `METRICS`, `CHECKSIG`, `RLS`, `CHANNELS`, `IGNORMQTT`, `OKMQTT`, `NODECRC`, `FEATURES` | Existen en 2.8.101 | `LCS`/`FEATURES` no en 2.8.005 |
| `NODECRC` | Confirmado | devuelve el node_num del emisor: node_num = crc32(clave) |
| Pacing difusión | Confirmado | 2.º `/nexus` a 1 s se descarta |
| A6 dos dirigidos a 1 s | Solo 1 de 2 responde (reproducible, 3 de 3) | mantener 10 s |
| H7 | Solo por fuente | los nodos corren build privada (`Flags: BURN+AIRTAG`); no se probaron comandos privados |

Formatos reales capturados (material para parsers): `NEIGHBORS`
(`JT Neighbors (0-hop):` + `!id:NOMBRE(snr)`), `INFRA` (**cabecera `JT JT Infrastructure:`
duplicada**, tolerar), `NODES28` (`11/109 matched`, solo 11 nodos con estructura 2.8),
`HOPSTATS`, `RELAYS`, `LCS`, `FEATURES`, `VAULT`, `TRUSTED`, `MODULES`, `HOPMATRIX`,
`FULLCONFIGDUMP` (13 mensajes) y `TRACE` (`JT TRACE (1.6s):` con ida y vuelta + SNR).

### 7.1 Seguridad, `-local` y marcadores (validado a mano, 2026-10-14)

Secuencia por la malla desde el X1 al T1000 (2.8.101), con reversión por reinicio
USB del T1000 (RAM; nada se guardó; estado final verificado: `REQ_SIG:off`, `SK:0/4`):

| Paso | Respuesta |
|---|---|
| `SKEY 1 <clave pública del emisor, hex 64>` | `🔒 JT: SKEY 1 updated.` |
| `SECURITY RSIG ON` | `🔒 JT SECURITY: … REQ_SIG:ON …` |
| `VERSION` | `🔒 JT VERSION: 2.8.101.08c204f` |
| `SKEY 1 OFF` | `🟢 JT: SKEY 1 wiped.` (la clave ya no cuenta al marcar) |
| `VERSION` (sin clave de confianza) | `JT SECURITY: rejected — signature required (REQ_SIG)` — **sin marcador** |

- **H3 confirmada:** 🔒 aparece cuando el firmante está en admin/secondary; 🟢 si no.
  La pasarela debe registrar su clave con `SKEY` para operar un nodo con `REQ_SIG`.
- **Rechazo sin marcador:** el parser lo reconoce con o sin marcador y el backend lo
  guarda como estado `rejected` (nuevo), distinto de `confirmed`.
- **M7:** `SETROLE <mismo rol>` → `JT: Role updated to 1 (1).`, sin reinicio.
- **Hallazgo — `/nexus-local` por API serie es un no-op:** `DROP TR` mandado como
  `/nexus-local` por el USB del T1000 no aplicó nada ni respondió (también 0
  respuestas en la captura del 2026-09-28 con 2.7.268). El destino «Local» de
  MeshSentinel (`-local` vía el USB de la pasarela) no hace nada observable.
  Pendiente decidir: ocultarlo o sustituirlo por `-node <propio>`.

### 7.2 Destino «Local» sustituido y parsers nuevos (2026-10-14)

- **Local → `-node <nombre corto del nodo local>`** (`resolve_local_target`, un solo punto):
  verificado en hardware que el nodo ejecuta el texto que sale de su propia API cuando se
  le dirige por su nombre corto o su id (`DROP TR`, `UPTIME`, `DROPS`, `UNDROP TR`; las
  respuestas llevan 🔴 porque el comando es interno y sin firma). Si la pasarela aún no
  informó de su nodo local, la operación se rechaza con un error claro.
- **Parsers con capturas reales:** `NEIGHBORS`, `INFRA` (cabecera `JT JT` duplicada),
  `NODES28` (filas pegadas), `HOPSTATS`, `RELAYS`, `LORACHIPSTATS`, `FEATURES`, `VAULT`,
  `TRUSTED`, `MODULES`, `HOPMATRIX` y `TRACE`. `TRACE` responde en dos mensajes: el
  `Starting trace…` es `interim` y NO cierra la operación; el resultado (ida, vuelta,
  SNR) la confirma. `METRICS` con datos y `FULLCONFIGDUMP` siguen sin parser (sin captura
  con valores / formato extenso).

# Guía de aceptación — JenTastic-Nexus: interruptor global + detección de nodos JT + cola de operaciones

Cierra los puntos 6, 7 y 8 del encargo original de administración Nexus
(ADR 0027).

## Qué se puede probar

1. **Interruptor global** (Ajustes → JenTastic-Nexus, solo administradores):
   - Con el modo apagado (por defecto), la sección de detección no aparece
     en absoluto — solo el propio interruptor.
   - Al activarlo, aparece de inmediato la sección "Detección de nodos JT"
     sin recargar la página.
   - `GET /api/v1/nexus/mode` refleja el estado; `POST /api/v1/nexus/scan`
     devuelve 404 con el modo apagado, incluso con una pasarela válida.

2. **Detección (solo sugiere)**:
   - Con el modo activado, elegir una pasarela conectada y pulsar "Buscar
     nodos JT". El botón queda en "Buscando (30 s)…" durante la ventana.
   - Con el simulador (`GATEWAY_TRANSPORT=simulated`), dos nodos simulados
     (excluyendo siempre el nodo local de la pasarela) responden con
     formato real de campo (`JT INFO:\n!id [short]\nVer: ...\nRole: ...\n
     MAC: ...`) tras un jitter de 0.5–2.5 s.
   - Con hardware real: solo responden nodos que de verdad corran
     JenTastic-Nexus y tengan el canal "Nexus"/"JenT" configurado — el
     gateway lo detecta por nombre, nunca por índice fijo; sin ese canal,
     la pasarela rechaza el envío (log `send_text_rejected`) y el
     escaneo no encuentra nada, no falla con error.
   - Los candidatos aparecen en una tabla (nombre corto, id, versión, rol,
     marcador 🟢/🔴 de firma si el nodo lo incluye). **Ninguno se marca
     solo.**
   - Un nodo ya marcado como Nexus aparece con el chip "ya marcado" en vez
     de los botones Marcar/Descartar.
   - "Marcar" hace `PUT /nodes/{id}/nexus {value: true}` y quita esa fila
     de la lista de sugerencias. "Descartar" solo la quita de la vista,
     sin tocar nada en el backend.
   - Repetir un escaneo en la misma pasarela antes de 2 minutos devuelve
     429 con el tiempo de espera restante (protección de tiempo de aire,
     D1 del prompt de implementación).

3. **Marcado independiente del escaneo**: `PUT /nodes/{id}/nexus` funciona
   igual sin haber escaneado nunca (marcado manual directo, vía API — sin
   atajo en la UI todavía para marcar sin pasar por una sugerencia).

4. **Los upserts de avistamiento nunca tocan la marca** (mismo criterio que
   `is_favorite`/`is_ignored`, M1.2) — cubierto por
   `test_scan_does_not_mark_any_node` y el propio `_NODE_SIGHTING_FIELDS`
   sin `is_nexus`.

5. **Cola de operaciones** (sección "Operaciones" en Ajustes → JenTastic-
   Nexus, bajo la detección): elegir pasarela, tipo de destino
   (difusión/local/nodo/MAC/grupo), comando (texto libre, p. ej. `STATS`) y
   argumentos opcionales, "Previsualizar" — muestra el texto exacto que se
   enviaría y, si el comando es destructivo (`REBOOT`, `NAME`, `OWNER`,
   `ZH CLEAR`/`IMPORT`, `SETLORA`, `TX OFF`, `SETSYNCWORD` distinto de
   0x2B…), exige teclear el destino (o "BROADCAST") para habilitar
   "Encolar". El historial de abajo se actualiza solo cada 3 s y muestra el
   texto, el estado (Pendiente/Enviado/Confirmado/Sin respuesta) y, al
   hacer clic en una fila con respuesta, el texto crudo y los datos
   estructurados si el parser los reconoce.
   - Con el simulador: mandar `INFO` en difusión a través del formulario
     debería confirmarse en pocos segundos (los nodos simulados responden
     con jitter de 0.5-2.5 s).
   - Un comando a un nodo inexistente (nombre corto que no responde) debe
     quedar "Sin respuesta" pasados ~30 s.

6. **Pestaña "JenTastic-Nexus" en el Inspector** (punto 7): abrir el
   Inspector de un nodo marcado como Nexus (chip/gato visible) con el modo
   global activado — aparece una pestaña "JenTastic-Nexus" junto a
   "Operaciones" (el pipeline nativo AdminMessage/PKC, sin relación). El
   formulario es el mismo que en Ajustes pero con el destino ya fijado a
   este nodo (`-node <shortname>`, sin selector de tipo de destino).
   - Con un nodo SIN marcar, o con el modo global apagado, la pestaña no
     aparece en absoluto.
   - Si desmarcas el nodo (o apagas el modo) mientras esa pestaña está
     abierta, el Inspector cae a "Actividad" en vez de quedarse en una
     pestaña que ya no debería existir.
   - El historial de esta pestaña muestra solo las operaciones dirigidas a
     ESTE nodo (`target_kind=node`, `target_value=<su nombre corto>`), sin
     importar por qué pasarela se enviaron.

7. **Seguridad (SECURITY/ALLOW_DM)** — en la pestaña JenTastic-Nexus del
   Inspector: "Leer estado" encola un `SECURITY` real y, en unos segundos,
   muestra el bitmask (REQ_SIG/ALLOW_DM/SILENT y, si el nodo es de build
   privada, también FAV_NX/FAV_TR/BYPASS_RP). Con `ALLOW_DM` en "off"
   aparece un aviso y un botón "Preparar activación" que solo rellena el
   formulario de abajo con `SECURITY ALLOW_DM on` — sigue habiendo que
   previsualizar y encolar a mano.

8. **Perfil de nodo (CONFIG/SETCONFIG)** — misma pestaña: "Leer
   configuración" muestra los valores actuales (NI, telemetría D/E/P,
   posición, SMART/FIXED/GPS, ubicación fija, rol de solo lectura). Cada
   campo editable tiene su propio input y un botón "Preparar cambio" que
   precarga `SETCONFIG <CAMPO> <valor>` en el formulario genérico. Rol y
   LoRa manual no aparecen como editables (confirmado por captura real que
   `SETROLE`/`SETLORA` no existen en el firmware probado).

9. **Gato en el marcador del Mapa** — con el modo global activado, un nodo
   marcado como Nexus muestra el gato en pixel-art junto a su marcador
   (abajo a la izquierda, para no chocar con el badge de redundancia).

## Fuera de alcance de esta fase (con motivo)

- ~~Insignia visual de "nodo Nexus" en Flota/Mapa~~ implementada
  (2026-09-29, completada en el Mapa el mismo día que los puntos 7-9):
  gato en pixel-art (`NexusCatIcon`, derivado del logo real del firmware
  que aportó el usuario) en Flota (roster plano y bloques), cabecera del
  Inspector y marcador del Mapa — visible solo con el flag global ON y el
  nodo marcado, nunca uno sin el otro.
- Autodetección pasiva (D3 del prompt: proponer un nodo si se le oye hablar
  con firma `JT ...:` sin haber escaneado) — solo se implementó la
  detección activa (D1, botón).

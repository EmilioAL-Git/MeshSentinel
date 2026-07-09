# ADR 0019 — Favoritos e Ignorados remotos (M4.1)

- Estado: Aceptado (2026-07-09)
- Complementa: ADR 0013 (pipeline), ADR 0014 (verify), ADR 0016 (Batch Engine)

## Contexto

Meshtastic permite marcar nodos como favorito/ignorado en la NodeDB de un
dispositivo remoto (`AdminMessage.set_favorite_node` / `remove_favorite_node` /
`set_ignored_node` / `remove_ignored_node`), pero el firmware **no expone
ninguna forma de leer** esa lista de vuelta. El patrón de M1.3/M1.4
(GET-SET-GET de verificación) no es aplicable: solo existe el ACK/NAK del
firmware al recibir el AdminMessage.

Además, el firmware puede ignorar `set_favorite_node`/`set_ignored_node` si el
nodo referenciado no está en su NodeDB local. Se necesita una forma de "dar a
conocer" ese nodo primero, opcional y bajo demanda del operador.

## Decisión

1. **Nuevo tipo de SET sin verificación por lectura ("ack-only")**: cuatro
   operaciones (`favorite.set`, `favorite.remove`, `ignored.set`,
   `ignored.remove`) que solo esperan el ACK/NAK de la capa de transporte
   (`onAckNak`, ya usado internamente por la librería oficial). El gateway
   sigue calculando `result.verify`, pero **siempre** `"unavailable"` (nunca
   `"confirmed"`/`"mismatch"`, no hay lectura posible). El backend ya mapea
   `verify == "unavailable"` a `succeeded_unconfirmed` (ADR 0014, sin cambios
   de código): ese es el estado terminal máximo alcanzable.
   - `OperationSpec` gana un campo `ack_only: bool` para que la UI adapte el
     texto de confirmación (no promete una verificación que no existe).
2. **Terminología de cara al operador**: dentro del panel dedicado de M4.1
   (favoritos/ignorados remotos) nunca se usa "succeeded_unconfirmed" ni
   "verificado". Se traduce a **Pendiente / Enviado / Confirmado / Error**,
   con ayuda explícita: "Confirmado" = el firmware aceptó la operación
   (ACK recibido), **no** que el NOC haya podido releer la NodeDB remota.
   Esta traducción es local a ese panel; el vocabulario existente del tab
   "Operaciones" (succeeded/succeeded_unconfirmed/verify_failed) no cambia,
   porque allí sí distingue información real para los SET verificables
   existentes (M1.3/M1.4).
3. **Sin tabla nueva de estado**: el estado de sincronización remota
   (Pendiente/Enviado/Confirmado/Error) se **deriva** de la última
   `AdminOperation` de los tipos relevantes para `(target_node_id,
   subject_node_id)`, vía `application/admin/remote_flags.py`. Cero esquema
   nuevo; reutiliza el historial de auditoría ya existente. Las columnas
   locales `nodes.is_favorite`/`is_ignored` (M1.2) quedan completamente
   intactas y sin relación con este estado — son conceptos distintos
   (filtro/organización propios del NOC vs. NodeDB del firmware remoto).
4. **`contact.add` (`SharedContact`/`add_contact`) — separado deliberadamente
   de NODEINFO_APP**: se evaluó y se descartó enviar un paquete NODEINFO_APP
   construido a mano con los datos de un nodo tercero — **no funciona**, el
   campo `from` del paquete lo fija el firmware del dispositivo conectado al
   transmitir; el nodo destino interpretaría el payload como si fuera la
   identidad del propio gateway, corrompiendo su entrada en la NodeDB remota.
   Son dos mecanismos distintos del protocolo y deben quedar nombrados sin
   ambigüedad: NODEINFO_APP es el broadcast normal de identidad (ya
   decodificado en `gateway/decoder/meshtastic.py`, sin relación con esto);
   `AdminMessage.add_contact`/`SharedContact` es la vía de administración
   remota correcta y ya prevista por el protocolo (`node_num`,
   `user{id, long_name, short_name, hw_model, public_key}`) — un admin
   message explícito ("añade este contacto"), no una suplantación de origen.
   **Convención de nombres, en adelante y para siempre**: código, comentarios,
   ADRs y documentación se refieren a esta operación únicamente como
   `contact.add` / `SharedContact` / `add_contact` — nunca como "NodeInfo" ni
   variantes ("NodeInfo previo", "ficha NodeInfo", etc.). La UI puede usar
   texto en lenguaje natural ("ficha del nodo", "información del nodo") pero
   sin sugerir que se envía un NODEINFO_APP. Nueva operación
   **`contact.add`** (`kind="action"`, `ack_only`),
   construida enteramente por el backend a partir de los datos ya conocidos
   del nodo sujeto en el Node Registry (no hace falta leer nada del nodo
   destino). Encapsulado en `gateway/decoder/admin.py` + `usb.py`; reemplazable
   sin tocar el registro si la librería añade soporte oficial de más alto
   nivel en el futuro.
   - Checkbox "Enviar previamente una ficha de contacto del nodo
     seleccionado", desactivado por defecto, nunca automático.
5. **Orquestación vía Batch Engine (ADR 0016), sin excepción**: encolar un
   favorito/ignorado —con o sin ficha de contacto previa— crea **siempre** un
   lote de 1 nodo mediante `BatchService.create_planned` (con 1 o 2
   `PlannedOperation`, mismo `target_node_id`, orden contacto→flag). Un lote
   de un único nodo hoy es, por diseño, el caso trivial de lo que en una fase
   posterior serán lotes de N nodos (sincronización masiva) sin cambiar el
   motor. Auditoría separada por fila de `admin_operations` (una operación
   `contact.add` + una operación `favorite.set`/`ignored.set`/etc.).
6. **Subject vs target**: en estas operaciones `target_node_id` es el nodo
   cuya NodeDB se modifica (donde se ejecuta el AdminMessage) y
   `subject_node_id` (parámetro nuevo del registro) es el nodo que se marca
   como favorito/ignorado en esa NodeDB. Desde el detalle de un nodo (target
   implícito = el nodo abierto), el operador elige el subject de un selector
   de nodos conocidos.

## Consecuencias

- Cero migraciones. Cero cambios al pipeline de scheduler/tracker/watchdog: el
  mapeo `verify: "unavailable" → succeeded_unconfirmed` ya existente cubre el
  caso sin tocar `service.py`.
- Preparado para fase futura (sin implementarla): sincronizar/resincronizar
  favoritos e ignorados a N nodos, comparar estado local vs. última operación
  conocida, y multi-pasarela — todo ello ya cabe en `BatchScope`/
  `BatchService.create_planned` sin rediseño.
- Limitación asumida y documentada: "Confirmado" es un techo de certeza más
  bajo que en los SET verificables (M1.3); es inherente al firmware, no una
  carencia del NOC.

## Errata (2026-07-09): ACK implícito confundido con ACK confirmado

Bug encontrado en validación de M4.2 por el usuario: favoritos remotos se
aplicaban correctamente en el dispositivo, pero ignorados remotos se
marcaban "Confirmado" sin haberse aplicado de verdad. Causa: `_ack_roundtrip`
(`gateway/transports/usb.py`) solo miraba `routing.errorReason == "NONE"`
para decidir `ack: true`. Pero la propia librería oficial (`Node.onAckNak`)
distingue dos casos cuando `errorReason == "NONE"`: si `packet["from"]`
coincide con el nodo local, es un **ACK implícito** — el radio local se rindió
tras agotar sus reintentos y generó una respuesta sintética ("Received an
implicit ACK. Packet will likely arrive, but cannot be guaranteed."), sin
confirmación real de que el destino procesó el AdminMessage; si `from` es
distinto del nodo local, es un ACK real. Nuestro código trataba ambos casos
igual, inflando la confianza justo en el escenario ack-only donde no hay
ninguna otra verificación posible (a diferencia de los SET de M1.3, que sí
tienen GET de verificación como red de seguridad).

**Corrección**: `_ack_roundtrip` ahora replica la distinción de la librería.
Un ACK implícito se trata como `ack: false` (`error_reason:
"IMPLICIT_ACK_ONLY"`), lo que fuerza el reintento normal del pipeline (ADR
0013, backoff 10→300 s) en vez de marcar la operación como terminal
"Confirmado". Es coherente con lo observado manualmente por el usuario con
el CLI oficial: la operación necesitó varios reintentos (`NAK,
MAX_RETRANSMIT` ×3) antes de recibir un ACK genuino y aplicarse.

## Errata 2 (2026-07-09): `wantResponse=False` privaba de confirmación real

Tras la corrección anterior, `ignored.set` empezó a funcionar, pero
`ignored.remove` seguía sin aplicarse pese a recibir un ACK **no implícito**
(`packet["from"]` distinto del nodo local) en el primer intento. Causa raíz
más profunda: `_execute_ack_set` llamaba a `_sendAdmin(set_msg,
wantResponse=False, onResponse=on_ack)`, razonando que no había AdminMessage
de respuesta que correlacionar para estas operaciones. Pero
`want_response` en el `MeshPacket` no es solo eso: es el campo que activa el
seguimiento fiable de `mesh_interface.sendData` (reintentos por la propia
malla y generación de NAK/ACK reales) — con `wantResponse=False` nunca se
solicita al destino ninguna confirmación de verdad, así que cualquier "ack"
recibido (implícito o no) no era una señal fiable. `Node.setFavorite` /
`Node.setIgnored` en la librería oficial usan `wantResponse=True` (su valor
por defecto) precisamente por esto — el mismo camino con el que el CLI del
usuario, tras varios `NAK, MAX_RETRANSMIT`, consigue una confirmación real.

**Corrección**: `_execute_ack_set` pasa ahora `wantResponse=True`, igual que
los wrappers oficiales. Sin cambios de esquema (contrato v1, `verify:
"unavailable"` intactos) ni de la lógica de `_ack_roundtrip` de la errata
anterior — ambas correcciones son complementarias: una decide qué cuenta
como "ack verdadero" una vez recibido, la otra asegura que se solicita un
ack verdadero en primer lugar.

## Errata 3 (2026-07-09): el ACK implícito no predice el resultado — se
revierte su tratamiento como fallo

Con la errata 2 ya aplicada, `ignored.remove` recibió un ACK **implícito**
(`from` == nodo local) en el primer intento; la errata 1 lo trataba como
`ack: false`, forzando reintentos hasta agotar `max_attempts` y terminar en
`failed` — pero el usuario confirmó en la app que el nodo **sí** se había
quitado de ignorados. El mismo patrón (ACK implícito → aplicación real) ya
lo había mostrado el propio CLI oficial del usuario al reproducir el
problema (varios `NAK, MAX_RETRANSMIT` y luego "Received an implicit ACK...
[...]" tras el cual la operación sí se aplicó). Conclusión: el ACK implícito
no es una señal de fallo — es, literalmente, lo que dice el mensaje de la
librería: "probablemente llegue, pero no hay garantía". La errata 1 fue un
diagnóstico incompleto porque en ese momento seguía activo el bug de la
errata 2 (`wantResponse=False`), que sí garantizaba ausencia de confirmación
real; con `wantResponse=True` corregido, el implícito deja de ser un
indicador fiable de fallo y solo genera falsos negativos si se trata como
tal (retries innecesarios sobre la malla y operaciones marcadas "Error"
pese a haber funcionado).

**Corrección**: `_ack_roundtrip` ya no distingue implícito/real para decidir
`ack` — solo un NAK explícito (`errorReason != "NONE"`) cuenta como fallo.
El carácter implícito se sigue registrando (`error_reason: "IMPLICIT_ACK"`)
en logs y en el resultado para diagnóstico, pero ya no bloquea el estado
"Confirmado"/`succeeded_unconfirmed`. Techo de certeza asumido explícitamente
(§Consecuencias): en este mecanismo ack-only, sin verify de lectura posible,
no existe ninguna heurística de ACK/NAK que prediga con certeza el resultado
real en el firmware — es inherente a la ausencia de un GET, no algo que se
pueda seguir puliendo a base de heurísticas más finas sobre el ACK.

## Errata 4 (2026-07-09): reenvío redundante hasta agotar `max_attempts`

Dado el techo de certeza de la errata 3 (ningún ACK aislado garantiza
aplicación real), el usuario pidió mitigarlo por el lado práctico: que
favorito/ignorado remotos agoten siempre sus `max_attempts` (por defecto 3)
en vez de darse por terminados en el primer ACK. Es seguro porque
`favorite.set/remove` e `ignored.set/remove` son idempotentes en el
firmware (reenviar el mismo SET no tiene efectos secundarios) y el
pipeline ya tiene presupuesto de malla (rate limit) y 1-en-vuelo-por-gateway
que evitan saturarla.

**Cambio**: `OperationSpec` gana `always_resend: bool = False`, activado
solo en las cuatro operaciones de favorito/ignorado (no en `contact.add`,
fuera del pedido explícito del usuario). En
`AdminOperationService.handle_event`, cuando el resultado mapea a
`succeeded_unconfirmed` y la operación tiene `always_resend` y
`attempts < max_attempts`, NO se marca terminal: se reprograma como un
reenvío (mismo mecanismo de `pending` + `next_attempt_at` que ya usan los
reintentos por fallo, pero con una pausa fija de 5 s — no exponencial,
porque no es un reintento por error) hasta que se agoten los intentos, momento
en el que el último resultado se convierte en el estado terminal. Nuevo
evento de actividad `resend_scheduled` (aditivo, contrato v1 intacto) para
no confundirlo con `retry_scheduled` (que sí implica fallo). El badge
Pendiente/Enviado/Confirmado del panel de M4.2 refleja fielmente este ciclo:
solo llega a "Confirmado" tras el último intento, nunca antes.

## Errata 5 (2026-07-09): el reenvío redundante reutilizaba un passkey PKC
de un solo uso → `ADMIN_BAD_SESSION_KEY`

Consecuencia inmediata de la errata 4: `node.ensureSessionKey()` (librería
oficial) es un no-op si el nodo ya tiene un `adminSessionPassKey` cacheado
en memoria del proceso — comprueba que exista, no lo renueva. El firmware
trata ese passkey como un nonce de un solo uso (protección anti-replay del
canal admin): el primer intento del reenvío redundante lo consume, y los
intentos 2 y 3 lo reenviaban sin saberlo, así que el firmware los rechazaba
con NAK `ADMIN_BAD_SESSION_KEY` — paradójicamente convirtiendo una operación
que probablemente ya había tenido éxito en el intento 1 en un "failed" final
tras agotar los 3 intentos con ese error.

**Corrección**: `_execute_ack_set` limpia la entrada
`adminSessionPassKey` de la caché de la librería (`iface._getOrCreateByNum`)
antes de cada intento (primero o reenvío), forzando que `ensureSessionKey()`
pida un passkey nuevo cada vez en vez de reutilizar uno potencialmente ya
consumido. Coste: un roundtrip extra de `SESSIONKEY_CONFIG` por intento;
aceptable frente al riesgo de reportar "failed" una operación que sí se
aplicó.

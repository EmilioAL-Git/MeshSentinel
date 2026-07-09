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
4. **"Enviar ficha de contacto" (antes "NodeInfo previo"), rediseñado tras
   investigación**: enviar un paquete NODEINFO_APP construido a mano con los
   datos de un nodo tercero **no funciona** — el campo `from` del paquete lo
   fija el firmware del dispositivo conectado al transmitir; el nodo destino
   interpretaría el payload como si fuera la identidad del propio gateway,
   corrompiendo su entrada en la NodeDB remota. La vía correcta y ya prevista
   por el protocolo es `AdminMessage.add_contact` con un `SharedContact`
   (`node_num`, `user{id, long_name, short_name, hw_model, public_key}`):
   un admin message explícito ("añade este contacto"), no una suplantación de
   origen. Nueva operación **`contact.add`** (`kind="action"`, `ack_only`),
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

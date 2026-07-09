# ADR 0020 — M4.2: Sincronización de favoritos e ignorados

- Estado: Aceptado (2026-07-09)
- Complementa: ADR 0013 (pipeline), ADR 0014 (verify), ADR 0016 (Batch Engine),
  ADR 0019 (Favoritos/ignorados remotos, M4.1)

## Contexto

M4.1 permitía marcar/quitar un favorito o ignorado remoto de un único sujeto a
la vez, sin visión de conjunto. M4.2 lo convierte en un sistema de
sincronización completo (ver/añadir/quitar todos los sujetos conocidos,
"Sincronizar" y "Reenviar pendientes") reutilizando íntegramente el pipeline,
el Batch Engine, la consola de actividad y el verify ack-only de M4.1 — sin
crear un mecanismo nuevo.

## Decisión

1. **El estado remoto se lee a través de un puerto, no de una tabla concreta.**
   `application/admin/remote_flag_sync.py` (núcleo puro) define el Protocol
   `RemoteFlagStateReader.list_known(target, flag_type)`; no importa
   SQLAlchemy ni conoce `admin_operations`. La única implementación hoy
   (`AdminOperationRemoteFlagStateReader` en `remote_flags.py`) deriva el
   estado del historial de `admin_operations`, igual que M4.1 — pero puede
   sustituirse en el futuro por una tabla materializada, una caché o una
   lectura real del firmware sin tocar el algoritmo de planificación.
2. **Modelo intermedio de plan, separado de su ejecución.** `compute_sync_plan`
   y `compute_resend_plan` devuelven un `RemoteFlagSyncPlan` (lista de
   `RemoteFlagPlanItem`: `ADD`/`REMOVE`/`CONTACT_ADD`, con `target_node_id`,
   `subject_node_id` y `target_gateway_id` opcional — siempre `None` hoy,
   reservado para Multi-Gateway). Un segundo paso, `to_planned_operations`,
   traduce el plan a `PlannedOperation` ya validadas por el registro. El plan
   en sí no ejecuta nada: queda disponible para simulación, vista previa,
   estadísticas o exportación sin recalcular la diferencia.
3. **"Sincronizar" y "Reenviar pendientes" son algoritmos distintos, no dos
   parámetros del mismo.**
   - `compute_sync_plan`: reconciliación — compara la última acción pedida por
     sujeto (`latest_action`, confirmada o no) contra el último estado
     **confirmado** conocido (`confirmed_action`); si coinciden, no genera
     nada (nunca reenvía una operación redundante).
   - `compute_resend_plan`: mecánico — no compara contra ningún objetivo,
     solo reemite la misma acción de los elementos actualmente `pending` o
     `error`. Nunca toca los `confirmed`.
   Comparten únicamente el puerto de lectura, no la decisión.
4. **`contact.add` se mantiene sin cambios de fondo** (ADR 0019 §4): sigue
   siendo `contact.add`/`SharedContact`/`add_contact`, nunca "NodeInfo". En
   `compute_sync_plan` se antepone opcionalmente un ítem `CONTACT_ADD` a cada
   `ADD` cuando se solicita (mismo checkbox "Enviar previamente la ficha de
   contacto", desactivado por defecto); `compute_resend_plan` no lo reemite
   (fuera de alcance: la ficha ya se considera entregada o irrelevante en un
   reintento mecánico).
5. **Todo sigue pasando por `BatchService.create_planned`** (ADR 0016 §5,
   ADR 0019 §5): cada "Sincronizar"/"Reenviar pendientes" crea **un único
   lote** con N `PlannedOperation` (una por sujeto, mismo `target_node_id`),
   igual que la sincronización de perfiles de M3. `operation_type` del lote
   es una etiqueta (`favorite.sync`, `ignored.resend`, …), sin significado
   para el motor. Si el plan resulta vacío, no se crea lote (`batch_id: null`).
6. **API**: `GET /admin/remote-flags/{node_id}/known?flag_type=` (lista
   completa, sustituye la consulta de un único sujeto de M4.1),
   `POST .../sync`, `POST .../resend-pending`; `POST .../queue` (M4.1) se
   mantiene igual para altas/bajas puntuales. Frontend: dos listas
   ("Favoritos conocidos" / "Ignorados conocidos") en el detalle de nodo, con
   alta/baja inline y botones de cabecera Sincronizar/Reenviar pendientes.

## Consecuencias

- Cero migraciones; cero tabla nueva.
- El servicio de planificación es 100% testeable sin base de datos real
  (basta un `RemoteFlagStateReader` de prueba), y queda preparado para
  operaciones masivas y Multi-Gateway sin rediseño — solo falta implementar
  un lector que agregue varios `target_node_id`/gateways, no cambiar el
  algoritmo.
- Limitación heredada de M4.1: "Confirmado" sigue siendo un techo de certeza
  más bajo que en los SET verificables (M1.3), inherente al firmware.

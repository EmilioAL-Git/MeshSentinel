# ADR 0017 — Consola de actividad: eventos de ciclo de vida backend→UI

- Estado: Aceptado (2026-07-09)
- Complementa: ADR 0003 (bus), ADR 0006 (contrato), ADR 0013 (pipeline), ADR 0016 (batches)

## Contexto

El operador necesita observar en tiempo real qué hace el sistema (operación
añadida a la cola, enviada al gateway, esperando respuesta, verificación,
reintentos, batches, conexiones USB de las pasarelas) sin leer logs técnicos.
Los eventos del gateway ya llegan a la UI por el hub WebSocket, pero las
transiciones que decide el backend (despacho, reintentos con backoff, veredicto
final tras verify, ciclo de vida de lotes) solo existían como logs.

## Decisión

1. **Sin segunda infraestructura de eventos**: se reutiliza el envelope v1 y el
   `ConnectionHub` WebSocket existente, con el mismo patrón que el broadcaster
   de alertas (ADR 0012). Un `ActivityPublisher` compartido
   (`noc/application/activity.py`) recibe el `hub.broadcast` en el arranque;
   sin adjuntar es no-op (tests, scripts).
2. **Solo hub, nunca Redis**: los eventos de actividad son informativos para la
   UI. No se publican en `noc:events`, por lo que el tracker no puede
   consumirlos ni crear bucles, y el contrato gateway↔backend queda intacto.
3. **Vocabulario aditivo**:
   - `admin.operation` gana estados backend con contexto completo (`node_id`,
     `operation_type`, `batch_id`, `attempts`): `created`, `dispatched`,
     `running`, `retry_scheduled` (con `delay_seconds`), `finished` (con
     `final_status` ya mapeado y `verify`). La UI ignora los eventos crudos del
     gateway (solo traen `operation_id`) y usa estos.
   - Nuevo `admin.batch` con estados `created|paused|resumed|cancelled|
     completed|completed_with_errors` (con `counts`).
   - Pasarelas/alertas/malla reutilizan los eventos ya existentes; los
     heartbeats `gateway.status` idénticos se deduplican en el cliente (solo se
     muestra el cambio de estado: conexión/desconexión/reconexión USB).
4. **Frontend**: buffer único en memoria (500 entradas) alimenta la vista
   «Actividad» (filtros por nodo, batch, pasarela y tipo; limpiar vista) y el
   feed del Dashboard (25 primeras). Sin peticiones HTTP adicionales ni
   persistencia: es un monitor de sesión, no un visor de logs.

## Consecuencias

- El operador ve el pipeline completo (cola → envío → respuesta → verificación
  → reintento/final) con los nombres de nodo resueltos.
- Los eventos de actividad se pierden al recargar la página (aceptado: la
  auditoría persistente ya existe en `admin_operations`/`admin_batches`).
- Emitir dentro de transacciones abiertas es aceptable (envío WS en memoria);
  si una transacción hiciera rollback tras emitir, la UI mostraría una entrada
  optimista — riesgo asumido por simplicidad.

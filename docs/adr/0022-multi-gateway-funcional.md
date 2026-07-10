# ADR 0022 — M6.2: Multi-Gateway funcional (enrutado, reparto, observaciones y simulador)

- Estado: Aceptado (2026-07-09)
- Complementa: ADR 0013 (pipeline de administración remota), ADR 0016 (Batch
  Engine), ADR 0021 (gestión de gateways), diseño `docs/design/m6-multi-gateway.md`
  (aprobado) y M6.1 (`node_gateway_links` + `select_primary_link`, migración 0009)

## Contexto

M6.1 dejó el modelo de datos N:M (`node_gateway_links`) y la función única de
ranking (`gateway_link_selection.select_primary_link`) que ya recalcula la
caché `nodes.gateway_id` (pasarela primaria). Pero el resto del sistema seguía
sin *usar* esa información: la administración remota y los lotes enrutaban por
la caché monovaluada, la UI no mostraba redundancia, y el simulador no podía
generar solape real entre pasarelas. El usuario pidió consolidar en una sola
fase (M6.2) la primera versión funcional completa de Multi-Gateway,
manteniendo el comportamiento exactamente igual con una sola pasarela.

## Decisión

1. **Enrutado en el momento de encolar, sin failover.**
   `application/admin/gateway_routing.py` (nuevo) resuelve la pasarela de una
   operación cuando esta ENTRA EN COLA, reutilizando `select_primary_link` con
   el filtro de candidatos del diseño §6: pasarela `connected` (heartbeat no
   stale), `enabled`, no eliminada, con enlace ACTIVO (umbral
   `node_offline_after_seconds`) hacia el nodo. Una vez creada la operación,
   su `gateway_id` no cambia (ADR 0013: cambiar de pasarela a mitad de
   reintentos podría duplicar un SET). El único punto de re-evaluación es el
   **reintento manual** del operador (`POST /admin/operations/{id}/retry`).

2. **Fallback a la caché = cero regresión mono-pasarela, con un límite.**
   El fallback a `nodes.gateway_id` solo se aplica cuando NINGÚN candidato
   pasa los filtros (con candidatos válidos jamás interviene) y nunca puede
   devolver una pasarela retirada de forma permanente: si su fila en
   `gateways` consta eliminada (borrado lógico) o deshabilitada, la selección
   devuelve `None` (operación no enrutable, 409/error de validación en los
   productores). Solo se permite el fallback con la pasarela
   operativa-pero-caída (se encola y despachará cuando vuelva — exactamente
   el comportamiento pre-M6.2) o sin fila en `gateways` todavía (arranque en
   frío, nunca ha enviado heartbeat). Los tests de M1–M4 pasan sin cambios
   por esta razón; `test_gateway_routing.py` cubre los cuatro casos.

3. **Todos los productores de operaciones pasan por la misma selección**:
   operaciones sueltas (`POST /admin/operations`), refresh/apply del editor de
   configuración, favoritos/ignorados remotos (queue/sync/resend),
   `BatchService.create()` (bulk, 2 consultas totales vía
   `select_gateways_for_nodes`) y la sincronización de perfiles. El reparto de
   lotes entre pasarelas emerge solo: `PlannedOperation.gateway_id` ya era
   por-operación (ADR 0016), ahora cada nodo obtiene SU mejor pasarela.

4. **Lectura/observabilidad**: `GET /nodes` adjunta `gateway_links` (todas
   las observaciones por pasarela, con `active` y `primary` calculados);
   `GET /nodes/{id}/gateways` gana los mismos campos; nuevo
   `GET /gateways/stats` (registrado antes de `/{gateway_id}`) con métricas
   derivadas puras (`application/gateway_stats.py`): nodos
   visibles/exclusivos/compartidos y última actividad por pasarela,
   `primary_for`, y redundancia global. Los nodos ignorados quedan fuera de
   los agregados (criterio M1.2); los enlaces stale no cuentan como
   redundancia pero sí para "última actividad".

5. **Simulador multi-instancia**: `sim_seed`/`sim_node_count` ya existían por
   proceso; se añaden `sim_shared_seed`/`sim_shared_node_count` — los nodos
   compartidos (SHRxx) se generan SOLO a partir de la semilla común, de modo
   que N procesos con el mismo `sim_shared_seed` ven exactamente los mismos
   nodos lógicos (mismos `node_id`) con señal distinta por proceso (rng por
   pasarela), poblando `node_gateway_links` con solape real. El nodo local es
   siempre exclusivo. Los 4 parámetros son configurables desde la app
   (`connection_params` del transporte `simulated`, `transport_manager`).
   Con `sim_shared_seed=0` (por defecto) la malla es idéntica a la anterior.

6. **UI**: pasarela primaria + contador de redundancia en la tabla de nodos;
   tabla "Observaciones por pasarela" en el detalle; badge numérico y lista de
   observaciones en el popup del mapa (marcador único por nodo); panel
   "Cobertura Multi-Gateway" en el Dashboard (solo visible con ≥2 pasarelas);
   columna "Pasarela" en Operaciones y en el monitor de Batches (+ línea de
   reparto por pasarela); insignia de pasarela por línea en la consola de
   actividad (el filtro por pasarela ya existía); tarjetas de Gateways con
   visibles/exclusivos/compartidos/última actividad; asistente "+ Añadir
   gateway" con selector explícito de candidato cuando hay ≥2 sin configurar
   y soporte de transporte simulado con sugerencia de semilla no usada.

## Fuera de alcance (decidido explícitamente por el usuario)

- Selección manual de pasarela por operación (el campo `target_gateway_id`
  de ADR 0020 sigue reservado, sin UI).
- Failover automático durante la vida de una operación.
- Alertas específicas de Multi-Gateway (`node_gateway_link_stale`, §5.2 del
  diseño) — pendiente de decidir con datos reales.
- Histórico de observaciones (serie temporal de RSSI/SNR por pasarela).
- Rate limit por pasarela (M6.5 del diseño): `count_dispatched_since` sigue
  siendo GLOBAL. Es un cambio de comportamiento (aumenta el throughput con N
  pasarelas) que el diseño exige aprobar explícitamente; hasta entonces el
  ETA global de lotes sigue siendo correcto tal cual está.

## Consecuencias

- Con una sola pasarela nada cambia de forma observable (fallback + no-op de
  la selección con candidato único + panel del Dashboard oculto).
- Con N pasarelas, los lotes se reparten y despachan en paralelo (el "1 en
  vuelo" ya era por-gateway), pero comparten el presupuesto global de
  ops/minuto hasta que se apruebe M6.5.
- La selección lee `gateways.status` del heartbeat: una pasarela recién
  caída puede ganar durante hasta `gateway_stale_after_seconds` (90 s). Se
  acepta: la operación quedará en cola/timeout y el reintento manual re-evalúa.

# M2 — Batch Engine: administración masiva

Valida el ciclo completo con el simulador (12 nodos) y después con hardware.

## A. Simulador

1. **Selección**: en Nodos, marcar 2 checkboxes sueltos → "Seleccionados: 2".
   "+ visibles" añade todos los filtrados; "Invertir" alterna; "+ favoritos"
   añade los ★; el checkbox de cabecera marca/desmarca visibles; "Limpiar" a 0.
   Combinar: filtrar por hardware TBEAM → "+ visibles" → quitar filtro →
   "+ favoritos" (criterios combinados).
2. **Simulación**: con ~6 nodos seleccionados, "Crear batch" → operación
   `module_config.set`, sección `telemetry`, campo `device_update_interval`,
   valor `900` → "Simular". Debe mostrar: elegibles, advertencia "sin conexión
   reciente" para nodos offline, verificación=sí, duración estimada
   (~6 ops × 10 s con rate 6/min = ~60 s). Nada se ha modificado aún.
3. **Ejecución**: escribir CONFIRMAR → "Ejecutar batch" → salta al monitor.
   Barra de progreso avanzando, "Procesando: <nodo>", velocidad, ETA
   descendente, chips por estado clicables (filtran la tabla de nodos).
   Cada fila expandible muestra previous/requested/verified.
4. **Pausa/Reanudación**: pausar a mitad → el contador de succeeded se detiene
   (la operación en vuelo termina; ninguna nueva se despacha). Reanudar →
   continúa donde estaba.
5. **Cancelación**: en otro batch, cancelar a mitad → las `pending` pasan a
   `cancelled`; la que estaba en vuelo termina normalmente y queda auditada;
   estado final del lote `cancelled` con finished_at.
6. **Finalización**: un batch que termina sin fallos → `completed` (verde);
   con algún timeout (el simulador pierde ~10%) → `completed_with_errors`.
7. **Historial**: la vista Batches lista todos, filtra por estado y tipo, y
   al abrir cualquiera se ve el detalle completo aunque haya terminado.
8. **Persistencia**: crear un batch de 10+ nodos y reiniciar el backend a
   mitad → al volver, continúa despachando (cola en BD).

## B. Hardware

1. Batch de `metadata.get` sobre todos los nodos administrables → inventario
   de firmware/hardware de la flota en el historial (cada resultado en su
   operación).
2. Batch de `module_config.set` (telemetry) sobre 2-3 nodos con admin_key →
   `completed`; verificar en el editor de configuración que el valor cambió.
3. Nodo sin admin_key incluido a propósito → su operación termina `timeout`
   tras reintentos y el lote termina `completed_with_errors` (el resto OK).

| Paso | OK/FALLO | Notas |
|---|---|---|
| A1–A8 | | |
| B1–B3 | | |

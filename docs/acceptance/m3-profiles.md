# M3 — Perfiles de configuración

Valida el ciclo completo con el simulador y después con hardware. Antes de
empezar conviene tener leída la configuración de algún nodo (pestaña
Configuración → Refrescar todo, o secciones sueltas): la comparación se hace
contra la última lectura conocida, nunca sondeando la malla.

## A. Consola de actividad (previo, ADR 0017)

1. Pestaña **Actividad**: al encolar cualquier operación se ve la secuencia
   completa: «añadida a la cola» → «enviada a la pasarela» → «en ejecución…
   esperando respuesta» → «completada» (o «reintento en Xs», «timeout»).
   En SETs con verify: «completada y verificada ✓» / «verificación fallida».
2. Filtros por nodo, batch, pasarela y tipo (chips); «Limpiar vista» vacía el
   buffer. El feed del Dashboard muestra lo mismo (25 últimos) y el botón
   «Consola →» salta a la vista completa.
3. Reiniciar el gateway USB: deben aparecer «conexión perdida — reintentando»
   y «conexión USB establecida ✓» (solo transiciones, no heartbeats).

## B. Perfiles — CRUD y versiones

1. **Crear desde nodo**: Perfiles → «+ Nuevo perfil» → nombre «Repetidor» →
   «copiar desde nodo» con un nodo ya leído → Copiar. El editor se rellena con
   su configuración; quitar los campos que no deban formar parte del perfil
   (un campo vacío = no gestionado). Crear perfil → detalle en v1.
2. **Crear desde cero**: otro perfil con 2-3 campos sueltos (p. ej.
   `telemetry.device_update_interval=900`, `display.screen_on_secs=60`).
   La sección `owner` no aparece: los nombres son identidad por nodo.
3. **Versionar**: «Editar (nueva versión)» → cambiar un valor → comentario →
   guardar. El historial muestra v1 y v2 (v2 actual); pulsar v1 muestra su
   contenido intacto y ofrece «Restaurar v1 como nueva versión» (crearía v3).
4. **Validación**: intentar guardar un valor inválido (enum inexistente vía
   API, o un texto en un campo numérico) → 422 sin efectos.

## C. Comparación

1. En el detalle del perfil → «Comparar con nodo» → elegir un nodo leído.
   Deben verse los contadores (iguales/distintos/sin datos) y, por defecto,
   **solo las diferencias**; el toggle muestra todo.
2. Un campo que el nodo tiene en default de fábrica (p. ej. un bool en false
   que el firmware omite) debe comparar como **igual** si el perfil pide ese
   default (semántica proto3: ausencia == default).
3. Secciones nunca leídas → «sin datos del nodo — refresca su configuración».
4. Se puede comparar contra cualquier versión del perfil (selector).

## D. Sincronización (vía Batch Engine)

1. «Sincronizar nodos» → seleccionar varios (chips con checkbox, «+ online») →
   **Simular sincronización**. La simulación no modifica nada y muestra por
   nodo: nº de cambios y secciones afectadas; los nodos ya conformes quedan
   excluidos («ya conforme con el perfil»); advertencia en nodos offline.
2. Confirmar con CONFIRMAR → salta al monitor de Batches: el lote se llama
   «Perfil <nombre> vN», tipo `profile.sync:<nombre> vN`, y sus operaciones
   son `config.set`/`module_config.set` normales (expandibles con
   previous/requested/verified). Pausa/reanudación/cancelación funcionan.
3. **Solo diferencias**: comprobar en las operaciones del lote que los params
   contienen únicamente los campos que diferían, no el perfil completo.
4. Al terminar, repetir la comparación → el nodo debe salir conforme ✓ y una
   nueva simulación debe excluirlo («ya conforme»).
5. **Secciones sin datos**: sincronizar contra un nodo sin lecturas → por
   defecto se omiten (aviso). Marcar «incluir secciones sin datos» → la
   simulación pasa a escribir el perfil completo en esas secciones (el
   gateway fusiona sobre su lectura previa, sin resetear el resto).
6. La consola de Actividad muestra todo el ciclo del lote y sus operaciones.

## E. Hardware real

Repetir B.1 (copiar desde el nodo real), C (comparar) y D con un solo nodo y
un cambio inocuo (p. ej. `display.screen_on_secs`): verificar que el nodo
refleja el cambio, que el verify confirma y que revertirlo (restaurar la
versión anterior y sincronizar) lo deja como estaba.

## Migración

`0007_config_profiles.py` (config_profiles + config_profile_versions); corre
automáticamente en el entrypoint del backend. Sin cambios de contrato v1.

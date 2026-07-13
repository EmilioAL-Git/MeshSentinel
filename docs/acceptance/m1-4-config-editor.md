# M1.4 — Editor completo de configuración

> **Histórico**: la vista "Configuración" sigue existiendo (re-cromada en
> v0.8.0), pero las referencias a "la vista Operaciones" corresponden a una
> pestaña ya fusionada en **Trabajos** (ver `docs/glossary.md`). El
> mecanismo del editor (esquema, apply, verify) no cambió.

Valida el editor de configuración generado a partir del esquema protobuf,
tanto con simulador como con hardware real. Sigue el patrón de M1.3: pre-read,
SET, settle, verify.

## A. Simulador

1. **Esquema**: la pestaña *Configuración* carga sin errores y muestra los
   grupos `General`, `Radio`, `Dispositivo`, `Seguridad`, `Ubicación`, `Módulos`.
   Cada sección (owner + 9 config + 16 module_config) aparece con su badge de
   riesgo (SAFE / WARNING / DANGEROUS).
2. **Refrescar todo**: al pulsar el botón, la vista *Operaciones* muestra
   `1 + 9 + 16 = 26` GETs `pending` → `queued` → `succeeded`. Al terminar, los
   valores actuales del nodo aparecen en cada tabla.
3. **Editar varios campos en secciones distintas** (p. ej. `owner.short_name`,
   `device.node_info_broadcast_secs`, `telemetry.device_update_interval`) y
   comprobar que aparecen en el resumen de cambios pendientes. El riesgo
   agregado se muestra correctamente.
4. **Aplicar cambios**: la confirmación exige teclear el node_id. Al confirmar
   se encolan N SETs (uno por sección) en el orden: owner → SAFE → ... → LoRa.
   Cada uno pasa a `succeeded` con `verify=confirmed`. La UI refleja el valor
   nuevo tras `refetchInterval` (10s).
5. **Validación**: intentar aplicar `lora.region = "MARTE"` → 422 sin encolar
   nada. Intentar `owner.short_name = "DEMASIADO"` → 422.
6. **Sin cambios**: modificar un campo y volver al valor actual → desaparece
   del resumen (`equalValues` funciona con enum/int/bool).

## B. Hardware

Requiere `admin_key` del nodo central en el nodo objetivo (firmware ≥ 2.5).

1. **Cambio seguro (SAFE)**: modificar `telemetry.device_update_interval` de
   300 a 900 → `succeeded` con verify por lectura posterior. En un móvil real
   se ve que la telemetría cambia de cadencia.
2. **Cambio combinado**: `owner.long_name` + `display.screen_on_secs` en un
   solo apply → dos SETs encolados en orden owner → display, ambos `succeeded`.
3. **Cambio WARNING**: `lora.hop_limit` de 3 a 5 → `succeeded` tras el
   settle_delay. **Revertir** para no dejar la malla alterada.
4. **Verificación no disponible**: apagar el nodo justo tras el apply → algún
   SET termina en `succeeded_unconfirmed` (morado). La UI lo distingue
   claramente de un `succeeded` real.
5. **Nodo sin admin_key**: cualquier SET termina en `timeout` en el pre-read,
   sin enviar el SET (comportamiento seguro heredado de M1.3).
6. **Merge del previous**: cambiar UN campo de `lora` y comprobar que el resto
   de `lora` (region, tx_power) permanece intacto tras el read-back. Si no fuese
   así, el pipeline resetearía a defaults del firmware; verificar mirando el
   valor antes/después.

| Paso | OK/FALLO | Notas |
|---|---|---|
| A1–A6 | | |
| B1–B6 | | |

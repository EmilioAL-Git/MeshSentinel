# M1.3 — Acceptance Test: primeras operaciones SET (seguras)

> **Histórico**: referencias a "la pestaña Operaciones" corresponden a una
> pestaña ya fusionada en **Trabajos** (ver `docs/glossary.md`). El flujo
> de confirmación y verificación read-back no cambió.

Valida el pipeline de escritura con verificación read-back. Primero simulador,
después hardware. Requiere `admin_key` del nodo central en los nodos objetivo.

## A. Simulador (`GATEWAY_TRANSPORT=simulator`)

1. **Confirmación obligatoria**: en Operaciones, elegir un nodo y `owner.set`,
   rellenar `short_name` (máx. 4). El botón dice "Revisar y confirmar…" y al
   pulsarlo aparece el panel de confirmación → hay que **teclear el node_id**
   para poder encolar. Cancelar y confirmar deben funcionar.
2. **owner.set confirmado**: encolar `short_name=NEW1`. Estado final
   `succeeded` (etiqueta "confirmada"). Al expandir: tres bloques — valor
   anterior (nombre original), solicitado y leído (NEW1). En ~15 s el nodo
   aparece renombrado en la tabla de Nodos (difunde su nueva identidad).
3. **position.set_fixed confirmado**: encolar lat/lon válidas → `succeeded`;
   el nodo se mueve a esas coordenadas en el Mapa.
4. **Validación de parámetros**: `short_name` de 5+ caracteres o latitud 95 →
   error 422 al encolar (no llega a la cola).
5. **Nodo inexistente en malla**: la operación SET termina en `timeout` tras
   reintentos ("node did not answer pre-read").

## B. Hardware (`GATEWAY_TRANSPORT=usb`)

1. **owner.set sobre nodo administrable**: cambiar `long_name` a un valor de
   prueba → logs del gateway: `usb.admin_sent` → `usb.admin_set_sent` →
   `usb.admin_verify ... verify=confirmed` → estado `succeeded` con los tres
   valores auditados. **Revertir después** con otro owner.set (reversibilidad).
2. **position.set_fixed**: fijar la posición real del nodo → `succeeded`
   (verify vía fixedPosition=true) o `succeeded_unconfirmed` si la relectura
   se pierde — ambos aceptables; el estado distingue el caso.
3. **Nodo sin admin_key**: owner.set → `timeout` en el pre-read, SIN enviar el
   SET (comportamiento esperado y seguro).
4. **Verify no disponible**: apagar el nodo justo tras encolar (ventana entre
   SET y relectura) → `succeeded_unconfirmed` (morado, "sin confirmar"), no
   `succeeded`. La UI distingue claramente enviado vs confirmado.

| Paso | OK/FALLO | Notas |
|---|---|---|
| A1–A5 | | |
| B1–B4 | | |

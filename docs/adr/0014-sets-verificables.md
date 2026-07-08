# ADR 0014 — SETs verificables (M1.3): read-back automático y veredicto en el resultado

- Estado: Aceptado (2026-07-08)
- Contexto de diseño: `docs/design/modulo1-administracion-remota.md` (§3.2, principio *delivered ≠ applied*)

## Contexto

Un SET sobre LoRa solo obtiene ACK de enrutado: el firmware no confirma que la
configuración se aplicó. El operador debe distinguir "comando enviado" de
"cambio realmente confirmado". Restricción de la fase: no modificar el contrato
de eventos v1.

## Decisión

1. **Pipeline SET en el gateway = GET previo → SET → GET de verificación**,
   ejecutado como UNA operación (una fila de historial con auditoría completa):
   - El **GET previo** audita el valor anterior y, de paso, **establece el
     session passkey PKC**: la librería lo almacena automáticamente de
     cualquier respuesta ADMIN_APP (`_onAdminReceive`), y `_sendAdmin` lo
     adjunta al SET. Si el GET previo no responde, la operación falla como
     `timeout` sin enviar el SET (sin sesión el SET no se autenticaría).
   - Tras el SET se espera `GATEWAY_SET_SETTLE_SECONDS` (3 s) y se relee.
2. **El contrato v1 no cambia**: el gateway publica `admin.operation` con
   `state=succeeded` y el veredicto viaja dentro de `result`:
   `{previous, requested, verified, verify: confirmed|mismatch|unavailable}`.
   El backend mapea a los estados finales `succeeded` / `succeeded_unconfirmed`
   / `verify_failed` (migración 0005 amplía la columna status).
3. **Sin reintento automático** de `verify_failed` ni `succeeded_unconfirmed`:
   el SET pudo aplicarse; reintentar duplicaría escrituras en la malla. El
   reintento es decisión manual del operador.
4. **Confirmación explícita en la UI** para todo `kind=set` (propiedad
   `requires_confirmation` del registro de capacidades): resumen de nodo,
   operación y parámetros + teclear el node_id. No se puede encolar una
   escritura con un clic accidental.
5. Operaciones de M1.3 (deliberadamente inofensivas): `owner.set`
   (short/long name, verify por `getOwnerResponse`) y `position.set_fixed`
   (verify parcial: `POSITION_CONFIG.fixedPosition=true`; las coordenadas no
   son legibles por admin GET — documentado como límite del firmware).

## Consecuencias

- El historial registra valor anterior, solicitado y leído: diagnóstico de
  malla y auditoría completa (requisito M1.3).
- Añadir un SET nuevo = entrada en el registro de capacidades + entrada en
  `SET_OPERATIONS` del decoder (build_set, verify_get, compare); el motor,
  el contrato y la UI no cambian.
- Las operaciones excluidas (región, canales, claves, reboot…) siguen sin
  existir en el registro: no se pueden invocar ni por API.

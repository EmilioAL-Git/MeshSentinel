# Notificaciones multi-proveedor — guía de aceptación

Ver ADR 0025 para el diseño completo. Vocabulario de la UI: **Integración**
= instancia de proveedor configurada (un webhook concreto, un bot de
Telegram concreto); **Canal** = agrupación lógica a la que apuntan las
reglas (p.ej. "Operadores", "Guardia").

## Conceptos clave a verificar

- Una regla **sin canales asignados** sigue difundiendo a todas las
  integraciones activas (`enabled=true`) — comportamiento idéntico al
  anterior a esta fase. Verifícalo con una instalación que ya tuviera
  canales de la Fase 3C: tras el `alembic upgrade head`, esos canales
  reaparecen como Integraciones y las reglas existentes (`channel_ids: []`)
  siguen notificando exactamente igual que antes.
- Una regla **con canales asignados** notifica SOLO a las integraciones de
  esos canales, sin duplicados aunque una integración pertenezca a dos
  canales de la misma regla.
- `validate()` de cada proveedor rechaza configuración incompleta al crear
  o editar (422 con el detalle del campo que falta) — nunca llega a
  guardarse una integración con `bot_token` vacío, por ejemplo.

## A. Migración

1. Sobre una BD con datos de la Fase 3C (canales `notification_channels`
   con `channel_type`/`config`), corre `alembic upgrade head`.
2. Verifica que los canales antiguos aparecen ahora en la pestaña Alertas →
   panel "Integraciones", con el mismo `name`/`enabled` y el tipo correcto
   (`webhook`/`ntfy`).
3. `alembic downgrade -1` sobre una copia de prueba debe restaurar el
   esquema exacto anterior (columnas `channel_type`/`config`, sin las 3
   tablas nuevas) — no lo hagas sobre la BD real, solo para confirmar
   reversibilidad.

## B. Integraciones (proveedores)

1. Pestaña Alertas → panel "Integraciones" → "+ Nueva". Elige "ntfy",
   deja el campo Topic vacío y confirma que el botón "Crear integración"
   queda deshabilitado (validación en cliente) — si fuerzas la petición
   igualmente (curl), el backend debe devolver 422 con
   `["Falta 'topic'"]`.
2. Crea una integración ntfy real (topic tuyo) y pulsa "Probar": debe
   llegar la notificación de prueba (`[TEST] INFO: Prueba de integración`)
   a tu dispositivo/cliente ntfy.
3. Crea una integración Telegram: necesitas un bot (`@BotFather`) y tu
   `chat_id`. Pulsa "Probar" y confirma que llega el mensaje con emoji ℹ️ y
   formato Markdown.
4. "Duplicar" una integración: debe crear una copia con
   `"<nombre> (copia)"`, misma configuración, editable por separado.
5. Desactiva una integración (checkbox) — no debe seguir recibiendo
   notificaciones aunque esté en un canal usado por una regla.

## C. Canales lógicos

1. Panel "Canales" → "+ Nuevo". Crea "Operadores" con 2 integraciones
   marcadas. Crea "Guardia" con 1 de esas mismas + otra distinta.
2. Edita "Operadores" y quita una integración — el cambio debe persistir
   (recarga y confirma).
3. Borra un canal usado por una regla: la regla debe seguir existiendo
   (sin ese canal en su lista) — nunca falla silenciosamente ni la borra.

## D. Reglas y enrutado

1. Edita una regla (p.ej. "Batería baja") y márcale el canal "Operadores".
   Guarda y confirma que la fila de la regla muestra el chip "✉ 1".
2. Fuerza la condición para que dispare la regla (batería <20%, o el umbral
   que hayas puesto). Confirma en los logs del backend (o directamente en
   el destino) que SOLO las integraciones de "Operadores" reciben el
   mensaje — las que no están en ningún canal de la regla no deben recibir
   nada.
3. Asigna también "Guardia" (que comparte una integración con
   "Operadores") a la misma regla y repite la prueba: esa integración
   compartida debe recibir el mensaje **una sola vez**, no dos.
4. Quita todos los canales de la regla (chip desaparece) y repite: debe
   volver el broadcast a todas las integraciones activas.

## E. Reglas por grupo (trabajo concurrente, ADR/diseño aparte)

Si tu build incluye ya `group_id` en las reglas (motor de reglas §1), el
enrutado por canal es ortogonal: una regla puede tener grupo Y canales a la
vez, sin interacción entre ambos mecanismos — confírmalo creando una regla
con ambos y verificando que se evalúa solo sobre el grupo Y notifica solo a
los canales asignados.

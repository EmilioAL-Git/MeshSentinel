# ADR 0025 — Notificaciones multi-proveedor: proveedores y canales lógicos

- Estado: Aceptado (2026-07-15)
- Complementa: ADR 0008/0012 (motor de alertas y canales originales)

## Contexto

Desde la Fase 3C el motor de alertas despachaba cada transición a TODOS los
`notification_channels` (`enabled=True`) sin distinción: una tabla con
`channel_type` ("webhook" | "ntfy") + `config` JSON, un `Protocol` con un
único método `send(alert, kind)`, y un registro extensible `CHANNEL_TYPES`.
No existía forma de dirigir una regla a un subconjunto de destinos ni de
tener dos instancias configuradas del mismo tipo de proveedor con nombres
significativos para el operador.

El usuario pidió ampliar el sistema a un modelo multi-proveedor extensible,
con Telegram como primer proveedor nuevo, separando dos conceptos que la
tabla original mezclaba:

1. La **instancia de proveedor configurada** (un webhook concreto, un bot de
   Telegram concreto).
2. El **canal lógico** al que las reglas apuntan (p.ej. "Operadores",
   "Guardia"), que agrupa 1+ instancias de proveedor.

## Decisión

### Modelo de datos

- `notification_providers` (renombrada desde `notification_channels`):
  instancia de proveedor. Columnas: `id`, `name` (unique), `provider`
  (registro extensible por string, renombrado desde `channel_type`),
  `configuration` (JSON, renombrado desde `config`), `enabled`,
  `created_at`/`updated_at` (nuevas).
- `notification_channels` (concepto NUEVO, reutiliza el nombre de tabla
  anterior tras el rename): canal lógico. `id`, `name` (unique),
  `description` (nullable), `created_at`/`updated_at`.
- `notification_channel_providers`: puente N:M canal↔proveedor (PK
  compuesta).
- `alert_rule_channels`: puente N:M regla↔canal (PK compuesta) — "no quiero
  limitaciones futuras" (pedido explícito del usuario): una regla puede
  apuntar a 0+ canales.

Migración `0018_notification_providers_channels.py` (tras `0017`, que
introdujo `alert_rules.group_id` en trabajo concurrente del usuario durante
esta misma fase): `op.rename_table` + `batch_alter_table` para el rename de
columnas de `notification_providers`, `op.create_table` para las 3 tablas
nuevas. `downgrade()` simétrico, verificado con SQLite real (upgrade head +
downgrade -1 sobre una BD limpia).

### Compatibilidad (sin cambio de comportamiento por defecto)

`AlertRule.channel_ids` (no es una columna propia — se carga/guarda vía
`alert_rule_channels`, mismo patrón que tags/grupos de nodos en M1.2): si
está vacío, el `NotificationDispatcher` hace el broadcast de siempre a todos
los `notification_providers` con `enabled=True` — ningún operador existente
nota el cambio hasta que asigna canales explícitamente a una regla. Si la
regla tiene canales, se envía solo a la unión deduplicada (por id de
proveedor) de los proveedores de esos canales — un proveedor presente en dos
canales de la misma regla no recibe el mensaje dos veces.

### Protocol ampliado

`NotificationProvider` (antes `NotificationChannel`) gana dos métodos sobre
el `send` original:

- `async def test(self) -> None`: construye y envía un mensaje de prueba
  canned internamente (`message.test_message()`), sin depender de una
  `Alert` externa — antes la ruta de test construía una `Alert` sintética a
  mano.
- `def validate(self) -> list[str]`: síncrona, solo mira la forma de
  `configuration` (nunca hace I/O de red); lista de errores vacía = válida.
  Se llama al crear/editar un proveedor y devuelve 422 con el detalle si
  falta algún campo requerido (p.ej. `bot_token` de Telegram).

### Mensaje desacoplado del proveedor

`noc.application.alerting.message`: `NotificationMessage` (dataclass
`slots=True, frozen=True`: `title`, `severity`, `kind`, `subject_label`,
`body`, `occurred_at`) + `render_message(alert, kind)` puro. Cada proveedor
formatea esa estructura neutra a su propio formato de cable (webhook: JSON,
mismo shape que antes salvo `subject` en vez de `subject_id`/`subject_type`
separados; ntfy: headers+body, prioridades por severidad intactas;
Telegram: texto Markdown con emoji por severidad 🚨/⚠️/ℹ️). Evita duplicar la
lógica de títulos/prefijos por `kind` en cada adapter — antes vivía repetida
en `ntfy.py` y `webhook.py`.

### Proveedores implementados

Solo Telegram se añade como proveedor nuevo (Bot API,
`POST https://api.telegram.org/bot{token}/sendMessage`, vía `httpx` — ya
dependencia del backend). `configuration: {bot_token, chat_id}`. Discord,
Slack, email, Matrix y Pushover NO se implementan; la arquitectura los
admite sin cambios en el motor ni en el dispatcher — añadir uno es una
entrada nueva en `noc.adapters.notifications.PROVIDERS`.

### API

- `/notification-providers` (GET/POST/PATCH/DELETE) +
  `/notification-providers/{id}/test` + `/notification-providers/{id}/
  duplicate` (crea una copia con `name + " (copia)"`).
- `/notification-channels` (GET/POST/PATCH/DELETE) para el canal lógico;
  el PATCH reemplaza `provider_ids` completo (borra e inserta).
- Rutas de escritura de ambos recursos, y de `/alert-rules` (que ahora
  acepta `channel_ids`), llevan `RequireAuthDep` — mismo criterio que ya
  regía los canales originales (el backend hace POST a URLs/APIs
  arbitrarias).
- Sin shim de compatibilidad para las rutas antiguas `/channels`: proyecto
  interno sin clientes externos, eliminadas sin más (convención del
  proyecto de no dejar código muerto).

### Frontend (vocabulario en español, sin tocar backend)

"Integración" = instancia de proveedor configurada (antes "canal" en la UI
de Fase 3C). "Canal" = el concepto lógico nuevo. `PROVIDER_FIELD_META` en
`AlertsView.tsx` (mismo patrón que `RULE_FIELD_META`) dirige qué campos
mostrar por tipo de proveedor sin lógica if/else dispersa. Selector de
canales en el editor de reglas (checkboxes; vacío = "todas las
integraciones activas", mensaje explícito en la UI del fallback de
compatibilidad).

## Consecuencias

- Los operadores existentes no notan ningún cambio de comportamiento hasta
  que asignan canales a una regla explícitamente.
- Añadir un proveedor nuevo (Discord, email...) sigue siendo un adapter
  nuevo registrado en `PROVIDERS`, sin tocar el motor de alertas, el
  dispatcher, ni el modelo de reglas.
- Un canal lógico borrado deja `alert_rule_channels` sin esas filas
  (`ondelete="CASCADE"` a nivel de FK; en SQLite el repo también borra las
  filas puente explícitamente antes del `DELETE` de la fila principal —
  SQLite no aplica `ON DELETE CASCADE` de verdad, mismo patrón que M1.2).
- El rate limit de administración remota y la correlación de alertas siguen
  fuera de alcance de esta fase.

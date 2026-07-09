# ADR 0018 — M3: Perfiles de configuración sobre la infraestructura existente

- Estado: Aceptado (2026-07-09)
- Complementa: ADR 0013 (pipeline), ADR 0014 (verify), ADR 0015 (esquema por metadatos), ADR 0016 (Batch Engine)

## Contexto

Se necesita definir configuraciones «tipo» (repetidor, sensor, móvil…),
versionarlas, compararlas contra cualquier nodo y sincronizar únicamente los
parámetros diferentes, sin crear un segundo mecanismo de ejecución.

## Decisión

1. **Modelo**: `config_profiles` (metadatos) + `config_profile_versions`
   (contenido `{section: {field: value}}`, inmutable, append-only). Editar un
   perfil = crear versión; restaurar una versión antigua = nueva versión con su
   contenido. `latest_version` se deriva con `max(version)` (sin contadores).
2. **Contenido validado por el esquema de M1.4** (`validate_field_value`): cero
   lógica por parámetro también en perfiles. La sección `owner` queda excluida:
   los nombres son identidad de cada nodo, no configuración de un tipo (y
   `owner.set` no admite bulk a propósito).
3. **Comparación** contra los snapshots ya existentes (última lectura GET
   correcta por sección, extraída del historial `admin_operations` — módulo
   compartido `config_state`). El diff entiende la semántica de `asDict` del
   firmware: claves camelCase y **omisión de defaults proto3** (ausencia de un
   campo en un snapshot == su default: bool False, num 0, str "", enum primer
   valor). Estados por campo: `equal | different | unknown` (sin snapshot).
4. **Sincronización = un batch estándar** (ADR 0016): el plan se recalcula en
   el servidor y genera operaciones `config.set`/`module_config.set` por nodo
   con SOLO los campos diferentes, ordenadas por riesgo (igual que
   /config/apply: lora/security al final). `BatchService.create_planned` es la
   única puerta de creación de lotes (también la usa el `create` uniforme de
   M2); el pipeline de ADR 0013 no distingue estos lotes: rate limit, merge
   sobre lectura previa en el gateway, verify read-back, reintentos, pausa/
   reanudación/cancelación y progreso funcionan sin cambios. El lote lleva
   `operation_type="profile.sync"` y `params={profile_id, profile_name,
   version}` solo como etiqueta/auditoría.
5. **Secciones sin snapshot**: no se puede calcular diff → por defecto se
   omiten con aviso («refresca la configuración»). Opcionalmente
   (`include_unknown=true`) se escribe el perfil completo en ellas — sigue
   siendo seguro porque el gateway fusiona el SET sobre su propia lectura
   previa (M1.4), pero se deja como decisión explícita del operador.
6. **Nodos ya conformes** quedan excluidos del lote (cero tráfico LoRa
   innecesario, principio de observador pasivo).

## Consecuencias

- La comparación es tan fresca como el último GET: la UI muestra cuándo se
  leyó cada sección y ofrece refrescar; no se sondea la malla nunca.
- Un perfil puede referirse a campos que un firmware antiguo no tenga: el
  gateway ignora campos desconocidos al construir el SET y el verify lo
  detectaría (`verify_failed`).
- `admin_batches.operation_type="profile.sync"` no existe en el registro de
  capacidades: es una etiqueta del lote, no una operación despachable — las
  operaciones reales del lote son siempre tipos registrados.

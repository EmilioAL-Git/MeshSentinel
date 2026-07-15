# Diseño: URLs compartibles (deep-linking)

> Decisión de arquitectura: ADR 0026. Este documento es el esquema operativo
> (parámetro a parámetro) y el plan de implementación por fases — se amplía
> sin necesidad de un ADR nuevo cada vez que se cablea una vista más.

## 1. Objetivo

Cualquier estado que un operador vea en pantalla —vista activa, nodo
abierto, filtros, capas del mapa, edición en curso— debe poder copiarse
como URL y, al abrirla (en otra pestaña, otro navegador, enviada a otra
persona), reproducir exactamente esa pantalla. Se excluye deliberadamente lo
que no es "un lugar" (selección de lote, wizards, la paleta ⌘K) — ver ADR
0026 §"Qué queda fuera".

## 2. Convención de nombres

- **Path**: `/{view}` — la vista activa, vocabulario de `View` en `App.tsx`.
- **Globales** (sin prefijo): `node`, `tab`, `focus`, `group`.
- **De vista** (prefijo `{view}.`): todo lo demás. El prefijo es literal en
  el nombre del parámetro (`nodes.q`, no anidado), para poder leer/escribir
  con `URLSearchParams` plano sin serialización propia.
- Arrays/sets se codifican como lista separada por comas (`activity.cat=mesh,gateway`).
- Booleanos: presencia = `1`, ausencia = parámetro no está (evita `?x=false`
  ambiguo con "no seteado"); ausencia siempre cae al valor por defecto de la
  vista, igual que hoy.
- Ningún parámetro se escribe en la URL si su valor coincide con el default
  de la vista — URLs cortas para el caso común, y el `resolveView`/parsers
  siguen funcionando si un usuario edita la URL a mano y omite todo.

## 3. Esquema completo

### 3.1 Globales (cualquier vista)

| Param | Tipo | Ejemplo | Sustituye a (hoy) | Notas |
|---|---|---|---|---|
| `node` | `node_id \| —` | `node=!8f3ac2d1` | `App.tsx:203 selected` | Abre el Inspector. `pushState`. |
| `tab` | enum `TabId` | `tab=telemetry` | `Inspector.tsx:249 usePersistedState("window.inspector.tab")` | Solo se lee/escribe si `node` está presente. La preferencia de `localStorage` se mantiene como *default* cuando se abre un nodo sin `tab` en la URL (ADR 0026: "cómo tengo montado mi puesto" también aplica a qué pestaña abre por defecto). |
| `focus` | `node_id \| —` | `focus=!8f3ac2d1` | `App.tsx:197 focus` (solo el `id`; `since` se recalcula a `Date.now()` al activarse desde la URL, igual que hoy al hacer clic en ◎) | `replaceState`. |
| `group` | `number \| —` | `group=12` | `GroupContext.tsx:29 activeGroupId` | La URL gana sobre `localStorage` al cargar; luego quedan sincronizados (ver ADR 0026 consecuencias). |

### 3.2 `/ops` (Centro — mapa + capas)

| Param | Tipo | Sustituye a | Notas |
|---|---|---|---|
| `map.layers` | lista | `LayerToggle`/`MapLayerState` (`showInfra/showGateways/showUsers/showFixed/showFavoritesOnly/showLinks/showNeighbors/showTraces/showRoutes/showCoverage`) | Solo se listan las capas ON que difieren del default (`DEFAULT_MAP_LAYERS`, `LayerToggle.tsx:31-43`). Ej.: `map.layers=neighbors,coverage`. |
| `map.color` | enum `MapColorMode` | `colorMode` | Omitido si es `status` (default). |
| `map.lat`, `map.lng`, `map.z` | número | viewport de Leaflet | Se actualizan con `moveend`/`zoomend` del mapa (throttle, `replaceState`), y se aplican con `flyTo`/`setView` al montar si están presentes. `⌖ Centrar` del Inspector pasa a escribir aquí en vez de (solo) `pendingCenter`. |

Migra también el bug de doble prefijo `noc.noc.map.layers` (ADR 0026):
`MapView.tsx:296` deja de usar `usePersistedState` para `layers` y pasa a
`useUrlParam`. `colorMode` igual.

### 3.3 `/nodes` (Flota)

| Param | Tipo | Sustituye a (`NodeFilterParams`, `App.tsx:124`) |
|---|---|---|
| `nodes.q` | string | `filters.q` |
| `nodes.online` | `1\|0` | `filters.online` |
| `nodes.favorite` | `1` | `filters.favorite` |
| `nodes.hw` | string | `filters.hw_model` |
| `nodes.tag` | string | `filters.tag` |
| `nodes.group` | number | `filters.group_id` (⚠ **no confundir con el `group` global** — es el filtro puntual de tabla, ya hoy independiente del grupo activo; nombre distinto a propósito) |
| `nodes.gw` | string | `filters.gateway_id` |
| `nodes.batlt` | number | `filters.battery_below` |
| `nodes.ignored` | `1` | `filters.include_ignored` |

`fleet.columns` (`usePersistedState`, columnas visibles de la tabla) se
queda en `localStorage` — es "cómo tengo montada la tabla", no "qué estoy
mirando" (ADR 0026).

### 3.4 `/jobs` (Trabajos)

| Param | Tipo | Sustituye a |
|---|---|---|
| `jobs.node` | `node_id` | `JobsView.tsx:452 nodeFilter` |
| `jobs.type` | string | `JobsView.tsx:453 typeFilter` |
| `jobs.gw` | string | `JobsView.tsx:454 gwFilter` |
| `jobs.batch` | number | `App.tsx:214 openBatchId` / `JobsView.tsx:456 expandedBatch` |

### 3.5 `/activity` (Registro)

| Param | Tipo | Sustituye a |
|---|---|---|
| `activity.node` | `node_id` | `nodeFilter` |
| `activity.gw` | string | `gatewayFilter` |
| `activity.q` | string | `search` (ya viaja al servidor — la URL queda coherente con lo que realmente se pidió, no con el valor sin debounce) |
| `activity.batch` | number | `batchFilter` |
| `activity.cat` | lista | `categories` (omitido si son todas — el default) |
| `activity.packet` | string | `packetFilter` |
| `activity.bursts` | `1\|0` | *Se queda en `localStorage`* (`activity.groupBursts`): es presentación, no filtro — mismo criterio que `fleet.columns`. |

Paginación (`before_id`) y pausa manual/automática del scroll **no** entran
en la URL (ADR 0026): son posición de lectura, no un filtro.

### 3.6 `/alerts` (Alertas)

| Param | Tipo | Sustituye a |
|---|---|---|
| `alerts.edit` | `rule:{id}\|provider:{id}\|channel:{id}\|new-rule\|new-provider\|new-channel` | `editingRuleId/creatingRule`, `editingProviderId/creatingProvider`, `editingChannelId/creatingChannel` (`AlertsView.tsx:752-779`) | Un único parámetro con prefijo de tipo — como mucho un editor abierto a la vez hoy, coherente con la UI actual. |

Los campos del formulario en curso (`severity`, `threshold`, borradores…)
NO se serializan: si se abre el enlace, el editor se abre con los valores
**actuales** de esa regla/proveedor/canal (comportamiento natural de
"editar esto"), no con un borrador a medio teclear de otra persona.

### 3.7 Resto de vistas (`/profiles`, `/config`, `/gateways`, `/users`, `/login-log`, `/settings`)

Auditadas (§6 paso 8). Resultado:

| Param | Vista | Sustituye a | Notas |
|---|---|---|---|
| `profiles.open` | `/profiles` | `ProfilesView.tsx openId` | Perfil abierto (detalle/comparación/sync). El modo `editor` (crear/nueva versión) se queda FUERA a propósito — mismo criterio que `alerts.edit`: es un borrador de formulario derivado del esquema, no "un lugar" con id propio. |

Revisados y **deliberadamente sin cablear** en esta fase (documentado para
no repetir la investigación mañana si se retoma):

- **`/config` (`ConfigEditor.tsx`)**: tiene su propio `nodeId` (qué nodo se
  está configurando) — se decidió **no** reutilizar el `node` global del
  Inspector para esto: abrir un enlace de Config no debería poder cambiar
  qué nodo tiene abierto el Inspector en otra parte de la pantalla (son dos
  "estoy mirando esto" independientes). Si se cablea en el futuro, necesita
  su propio parámetro con prefijo (`config.node`), nunca el global `node`.
- **`/gateways` (`GatewaysView.tsx`)**: el `expanded` de cada tarjeta es
  estado local *por instancia de componente* (una tarjeta por pasarela), no
  hay un único "id abierto" a nivel de vista como en Perfiles/Trabajos —
  cablearlo exigiría además pasar el `gateway_id` a cada tarjeta para poder
  comparar contra un parámetro `gateways.open`, cambio más invasivo que el
  resto de esta fase. Wizard de alta (`AddGatewayWizard`) excluido, mismo
  criterio que `BatchWizard`.
- **`/users`, `/login-log`, `/settings`**: sin estado de navegación propio
  detectado (listas/formularios simples, sin "elemento abierto" persistente
  hoy). Nada que cablear.

## 4. Piezas técnicas

### 4.1 `frontend/src/hooks/useUrlState.ts`

Store minúsculo sobre la History API, con la misma filosofía que
`usePersistedState.ts` (un hook pequeño, sin dependencia nueva):

- Un único listener de `popstate` + una función `notify()` que dispara
  todos los suscriptores (patrón `useSyncExternalStore`, ya nativo en
  React 18 — evita reinventar pub-sub).
- `getSearchParams()` centraliza el parseo de `window.location.search`.
- `setParam(key, value, { replace })`: clona los params actuales, aplica el
  cambio (o borra la clave si `value` es el default/`undefined`), construye
  la nueva URL con el **path actual sin tocar** y hace
  `history.pushState`/`replaceState` + `notify()`.
- `useUrlParam<T>(key, defaultValue, { replace, parse, serialize })`: hook
  genérico, análogo a `usePersistedState`. `parse`/`serialize` por defecto
  para `string`; variantes tipadas construidas encima:
  `useUrlFlag` (booleano `1`/ausente), `useUrlNumber`, `useUrlList`
  (array separado por comas).
- `useUrlView()`: caso especial (vive en el path, no en query) —
  `getView()`/`setView(view, {replace})`, reutiliza `resolveView()` de
  `App.tsx` (se mueve a un módulo compartido si hace falta importarlo desde
  el hook sin ciclo).

Ningún componente de vista debe tocar `window.history` directamente — todo
pasa por estos hooks, igual que hoy nada toca `localStorage` directamente
fuera de `usePersistedState`.

### 4.2 Orden de aplicación al montar

1. `useUrlView()` decide la vista inicial (si el path es `/`, default
   `"ops"`, `pushState` silencioso a `/ops` para que la barra de
   direcciones sea siempre representativa).
2. Los hooks de cada vista leen sus propios `{view}.*` al montar el
   componente de esa vista (no hace falta pre-cargarlos todos en `App.tsx`:
   solo la vista activa se monta, como ya ocurre hoy).
3. `group`/`node`/`focus` (globales) se leen en `App.tsx` una vez, al nivel
   actual donde ya viven sus `useState` — pasan a `useUrlParam`.

### 4.3 Compatibilidad con `GroupContext`

`GroupContext.tsx` compone los dos hooks en vez de elegir uno:
`usePersistedState("activeGroupId", null)` sigue existiendo (preferencia de
sesión sin enlace) y se añade `useUrlNumber("group", null)`;
`activeGroupId` efectivo = `urlGroupId ?? storedGroupId` (la URL manda solo
si el parámetro está presente; si no, cae a la preferencia guardada, sin
escribir nada en la URL todavía). `setActiveGroup` escribe en ambos sitios
a la vez. Implementado así en el piloto de esta sesión — más simple que
añadir un modo "espejo" genérico dentro de `useUrlParam`.

## 5. Qué NO se toca en esta fase (documentado, no implementado)

- `checkedIds` (selección de lote), `wizardOpen`/`AddGatewayWizard`,
  `paletteOpen` — ver ADR 0026.
- Posición/tamaño de `FloatingWindow` por id, columnas de Flota, pestaña
  Actividad/Chat del Registro (`registerTab`), hora UTC de la barra de
  estado, agrupación de ráfagas — se quedan en `usePersistedState` tal
  cual, son preferencias de puesto de trabajo, no de contenido.

## 6. Plan de implementación

1. **Esqueleto**: `useUrlState.ts` funcional. — ✅ hecho.
2. **Piloto**: `node`, `tab`, `focus`, `group` en `App.tsx` +
   `GroupContext.tsx` + `Inspector.tsx`. — ✅ hecho.
3. **`/ops` — mapa** (§3.2): capas + viewport, bug del doble prefijo
   corregido de paso. — ✅ hecho.
4. **`/nodes` — Flota** (§3.3). — ✅ hecho.
5. **`/jobs` — Trabajos** (§3.4), `openBatchId` retirado de `App.tsx` en
   favor de `jobs.batch`. — ✅ hecho.
6. **`/activity` — Registro** (§3.5). — ✅ hecho.
7. **`/alerts`** (§3.6). — ✅ hecho.
8. Auditoría de `/profiles`, `/config`, `/gateways`, `/users`,
   `/login-log`, `/settings` (§3.7). — ✅ hecho: `profiles.open` cableado;
   `/config`/`/gateways` revisados y dejados fuera con motivo documentado
   (no son casos de "un id, una vista" tan directos como el resto).
9. Guía de aceptación (`docs/acceptance/urls-compartibles.md`) — pendiente,
   siguiente paso de esta misma sesión.

Todas las fases 1-8 dejan el frontend funcional (build + tsc limpios,
verificado en cada paso).

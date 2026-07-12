# El Sitio como contexto — propuesta de diseño

Estado: **PROPUESTA — revisión 2, incorpora las decisiones del usuario tras
la primera lectura. No implementada, no aprobada.**

Este documento **no sustituye** a `docs/design/v0.7-centro-de-operaciones.md`
(sigue siendo la referencia normativa del Centro) — lo extiende. Cualquier
principio de v0.7 §2 que este documento roce se cita explícitamente; ninguno
se contradice sin decirlo.

**Cero cambios de arquitectura de fondo.** Todo lo propuesto se apoya en
modelo de datos, endpoints y mecanismos que ya existen (`groups`,
`group_members`, `apply_filters(group_id=...)`, `compute_multi_gateway_stats`,
Focus, Inspector, BatchWizard). Se cita el archivo:línea exacto de cada pieza
reutilizada en §10. La única adición de esquema propuesta es un campo opcional
(§2.2), aditiva y sin riesgo.

---

## 0. Cambio de revisión respecto a la v1

La v1 de este documento proponía "grupo activo" como una mejora de UX sobre
Flota. Tras la respuesta del usuario, el alcance sube un nivel: **no es un
cambio de vista, es un cambio de filosofía de producto.**

> MeshSentinel deja de estar centrado en "todos los nodos de la red". Pasa a
> estar centrado en "la infraestructura que yo administro".

Y se añade un concepto de producto nuevo: el grupo, de cara al operador, no
es una lista técnica — es un **Sitio**: una infraestructura Meshtastic
completa con sus propias pasarelas, su propia gente, sus propias
estadísticas y sus propias alertas. Esto se desarrolla en §2.

Las tres preguntas abiertas de la v1 quedan resueltas (§9):
1. Taxonomía → confirmada tal cual se propuso.
2. Primera ejecución sin sitios → degradación elegante, sin asistentes.
3. Sitios múltiples activos a la vez → **no**. Un único sitio activo.

---

## 1. Filosofía: de "lista de nodos" a "mi infraestructura"

La v0.7/v0.8 resolvieron cómo mostrar el estado de **toda** la red de un
vistazo (principio v0.7 §2.2: "el mapa es el centro del sistema"). Eso sigue
siendo correcto para una red de 20-100 nodos donde el operador gestiona
prácticamente todo lo que ve. Pero con **cientos o miles de nodos visibles**
—una malla Meshtastic es una red compartida; cualquier nodo con buena
recepción puede "verse"— ese modelo se invierte: la mayoría de lo que se
muestra no es responsabilidad del operador.

**Cambio de flujo mental:**

| Hoy (v0.8) | Propuesta |
|---|---|
| "Voy a Flota, filtro, busco mi nodo." | "Elijo mi Sitio. Ya estoy en mi infraestructura." |
| El filtro es una acción repetida cada sesión. | El Sitio activo es un **estado persistente**, se elige una vez por turno. |
| Toda vista parte de "toda la red" y se reduce. | Toda vista parte del **Sitio activo**, sin excepción salvo el modo "Todos" explícito. |
| Flota = tabla de nodos de la malla. | Flota = **representación de mi infraestructura**. |

Esto no descarta la red completa — sigue siendo necesaria para
descubrimiento, diagnóstico de vecinos, y construcción de sitios nuevos. Es
un **modo explícito** ("Todos"), nunca el estado por defecto una vez el
operador tiene al menos un Sitio configurado.

---

## 2. El Sitio: el grupo elevado a concepto de producto

### 2.1 Qué es

Técnicamente, un Sitio **es** un `group` (`groups` table, M1.2) — cero
concepto de dominio nuevo, cero migración obligatoria. Lo que cambia es el
**vocabulario y la identidad visual** de cara al operador, siguiendo
exactamente el mismo patrón que ya usa el producto: "Flota" es
vocabulario sobre `nodes`, "Trabajos" es vocabulario sobre `admin_operations`
+ `admin_batches` (v0.7.4), "Gateways" es vocabulario transporte-agnóstico
sobre transportes USB/TCP (M5) — nunca se renombra la tabla, se renombra la
palabra que ve el operador.

Un Sitio no es "un grupo de nodos" — es una **infraestructura Meshtastic
completa**, con:

```
🏔️ Repetidores Sierra
   ├── sus gateways       (bloque 🛰)
   ├── su infraestructura (bloque 📡)
   ├── sus nodos fijos    (bloque 📍)
   ├── sus usuarios       (bloque 👤)
   ├── sus estadísticas   (§7 — solo de este sitio)
   ├── sus alertas        (§6.4 — solo de este sitio)
   └── sus operaciones    (§6.5 — solo de este sitio)
```

Ejemplos reales del propio usuario: 🏔️ Repetidores Sierra, 🏡 Mi casa,
🚙 Vehículos, 🚒 Protección Civil, 📡 Red Albacete. Un operador puede
administrar varios sitios distintos (varios `group_id`), pero trabaja
**dentro de uno a la vez** (§9.3).

Esto convierte MeshSentinel de "visor de una red Meshtastic" a "herramienta
de gestión de una o varias infraestructuras Meshtastic" — el cambio de
personalidad que pide el usuario, y una base natural para funcionalidad
futura (comparar sitios, plantillas de sitio, permisos por sitio si algún
día hay multiusuario).

### 2.2 ¿Necesita el modelo de datos algo nuevo?

Prácticamente nada. Una única adición **opcional y aditiva**, propuesta para
la Fase A (§11): `groups.icon` (texto corto, nullable — un emoji o un
nombre de icono). Sin este campo el selector puede usar un icono genérico
(📁) para todo sitio sin personalizar; con él, cada sitio puede tener la
identidad visual de los ejemplos de arriba. No es bloqueante: se puede
implementar todo lo demás sin este campo y añadirlo después sin fricción.

No se propone ningún otro campo nuevo (`kind`, `filter_expr`, `is_critical`
ya existen y no se tocan).

---

## 3. Sitio activo: qué es y qué no es

**Sitio activo** = una referencia persistida a un `group_id` existente (o
`null` = modo "Todos"). Es un **scope de trabajo**, no una selección
efímera. Persiste entre sesiones (localStorage, `usePersistedState`, mismo
patrón que filtros/paneles de v0.7.0).

Distinto de **Focus** (v0.7.3, `FocusState { id, since }`,
`FocusChip.tsx:11-14`): Focus es "estoy mirando este nodo concreto ahora
mismo" — atención puntual, un solo nodo, puede apuntar a cualquier nodo de
la red, **incluso fuera del sitio activo** (confirmado por el usuario: un
vecino que retransmite tráfico, por ejemplo). Sitio activo es "esta es mi
infraestructura" — dura un turno completo, es un conjunto, y **filtra**
—no solo influye, filtra— qué se muestra por defecto en cada vista.

También distinto de **selección** (`checkedIds`, M2): sigue siendo efímera y
explícita por checkbox, ahora armada dentro del universo del Sitio activo.
Se limpia al cambiar de sitio (evita arrastre de contexto entre
infraestructuras distintas — el tipo de fallo de identidad diagnosticado en
la sesión anterior).

El Inspector (v0.7.2) sigue siendo global, sin restricción por sitio —
coherente con v0.7 §2.4 ("todo detalle abre el mismo inspector"): siempre se
puede inspeccionar cualquier nodo de la malla compartida.

---

## 4. El Sitio como filtro principal de toda la aplicación

Confirmado por el usuario: no es una influencia parcial, es **el filtro
principal**. Con un sitio activo, ninguna vista debería requerir que el
operador aplique un filtro adicional para dejar de ver la red ajena — el
filtrado por sitio ya lo hace por él, en todas partes:

| Vista | Comportamiento con sitio activo |
|---|---|
| Flota | Solo nodos del sitio, organizados por bloques (§6) |
| Mapa | `fitBounds` al sitio; resto de la red atenuada, nunca oculta (§6.3) |
| Estadísticas | Solo agregados del sitio (§7) |
| Alertas | Solo alertas de nodos del sitio, con badge aparte para el resto (§6.4) |
| Trabajos / Actividad | Solo target dentro del sitio, con badge aparte (§6.5) |
| Inspector | **Sin restricción** — global siempre (§3) |

La única vía para ver más allá del sitio activo es el botón **Todos**
explícito (§5), nunca un filtro que el operador tenga que reconstruir cada
sesión.

---

## 5. El selector: HUD, persistente, con escape rápido

```
┌──────────────────────────────────────────────────────────────────────────┐
│ MeshSentinel  ⛭ 2/2  ⚠ 1  ▶ 3   [ 🏔️ Repetidores Sierra (18) ▾ ] [Todos]  ⌘K  UTC…│
└──────────────────────────────────────────────────────────────────────────┘
                                    ▲                          ▲
                     selector persistido              botón de escape,
                     (usePersistedState)               siempre visible,
                                                        un clic → sitio=null
```

Al desplegar el selector:

```
┌───────────────────────────────────┐
│ 🏔️ Repetidores Sierra  (18)  ✓     │
│ 🏡 Mi casa              (4)        │
│ 🚙 Vehículos            (3)        │
│ 🚒 Protección Civil     (7)        │
│ 📡 Red Albacete         (52)       │
│ ─────────────────────────────────  │
│ 🌐 Todos los nodos (1,247)         │
│ ─────────────────────────────────  │
│ + Crear sitio…                     │
└───────────────────────────────────┘
```

El botón **[Todos]** junto al selector es el "botón rápido" pedido: no hace
falta abrir el desplegable para volver a la vista global, un único clic.
Cuando el sitio activo ya es "Todos", el botón queda deshabilitado/oculto
(no hay a dónde escapar).

---

## 6. Dentro de un Sitio: Flota como consola de infraestructura

Con un sitio activo, Flota deja de ser una tabla y pasa a organizarse por
**bloques taxonómicos plegables** — primero categorías, después nodos, tal
como pide el usuario.

```
┌ 🏔️ REPETIDORES SIERRA · 18 nodos, 16 online ───────────────────────────┐
│ KPIs: 🟢16 🔴2   🔋 78%med   📶 buena   ⛭ 2/2 gws   ⚠ 1 alerta         │
├──────────────────────────────────────────────────────────────────────┤
│ ▾ 🛰 GATEWAYS (2)                                    [seleccionar todo]│
│    ☐ 🟢 gw-01 · Potatomesh 1        🔋ext  📶●●●●  hace 4s   [⋮]      │
│    ☐ 🟢 gw-02 · emylio T1000-E      🔋87%  📶●●●○  hace 11s  [⋮]      │
├──────────────────────────────────────────────────────────────────────┤
│ ▾ 📡 INFRAESTRUCTURA (3)                             [seleccionar todo]│
│    ☐ 🟢 Repetidor Sierra            🔋ext  📶●●●●  hace 8s   [⋮]      │
│    ☐ 🟢 Torre Norte                 🔋ext  📶●●○○  hace 2m   [⋮]      │
│    ☐ 🔴 Nodo Solar          ⚠       🔋12%  📶●○○○  hace 3h   [⋮]      │
├──────────────────────────────────────────────────────────────────────┤
│ ▾ 📍 NODOS FIJOS (3)                                 [seleccionar todo]│
│    ☐ 🟢 Casa                        🔋93%  📶●●●●  hace 1m   [⋮]      │
│    ☐ 🟢 Oficina                     🔋ext  📶●●●●  hace 30s  [⋮]      │
│    ☐ 🟢 Taller                      🔋ext  📶●●●○  hace 50s  [⋮]      │
├──────────────────────────────────────────────────────────────────────┤
│ ▸ 👤 USUARIOS (9)                                    [seleccionar todo]│
│ ▸ ❓ SIN CLASIFICAR (1)                               [seleccionar todo]│
└──────────────────────────────────────────────────────────────────────┘
   ▾ = expandido, ▸ = plegado. [⋮] = acciones de fila (igual que hoy).
```

Con selección activa (cualquier bloque, o mixta entre bloques — sigue
siendo un `Set<node_id>`, sin cambios de modelo):

```
├──────────────────────────────────────────────────────────────────────┤
│ 5 nodos armados · + visibles · invertir · + favoritos · desarmar todo │
│                                           [ ▶ Iniciar (5) ]            │
└──────────────────────────────────────────────────────────────────────┘
```

`[seleccionar todo]` por bloque añade a `checkedIds` todos los `node_id` de
ese bloque — mismo mecanismo que "+ visibles" hoy (`FleetView.tsx:390`),
aplicado al subconjunto del bloque. Filtros/búsqueda (M1.2, `apply_filters`)
siguen disponibles dentro de un sitio, sin cambios.

### 6.1 Sin sitio activo ("Todos"): Flota se comporta exactamente como hoy

Sin excepciones ni asistentes — ver §9.1.

### 6.2 Taxonomía — solo tiene sentido dentro de un sitio

Confirmado por el usuario: **no se clasifica la red entera**, solo los
nodos del sitio activo. En modo "Todos" no hay bloques — sería clasificar
potencialmente miles de nodos ajenos sin ningún beneficio para el operador,
y contradiría la premisa completa del documento. La tabla de categorías y
sus señales de clasificación (`role`, cruce con `gateways.local_node_id`,
tag `fijo` como convención manual) se detalla en §8, sin cambios respecto a
la v1 de este documento.

### 6.3 Mapa

`fitBounds` al sitio al activarlo. Nodos fuera del sitio se **atenúan**
(reutiliza el mecanismo que Focus ya usa desde v0.7.3), nunca se ocultan —
el operador puede necesitar ver un vecino que hace de puente. Un nodo con
alerta activa nunca se atenúa, esté o no en el sitio (principio v0.7 §2.1,
"las alertas mandan").

### 6.4 Alertas

Bandeja por defecto = alertas de nodos del sitio activo. Contador aparte,
nunca fusionado, para lo que quede fuera ("+ N fuera de tu sitio") — nunca
un recuento que oculte silenciosamente una CRITICAL ajena (v0.7 §2.1).

### 6.5 Trabajos / Actividad

Filtro por defecto = operaciones/eventos cuyo `target_node_id` esté en el
sitio activo. `JobsView` y `ActivityConsole` ya tienen filtros por nodo/tipo/
gateway (`JobsView.tsx:443-461`, `ActivityPanel.tsx:52-65`) — añadir "sitio"
como filtro adicional es aditivo, mismo patrón que los existentes.

### 6.6 Selección y Focus

- `checkedIds` se limpia al cambiar de sitio activo.
- Si `focus.id` apunta a un nodo fuera del sitio activo, el chip de Focus se
  pinta con un indicador distinto (borde discontinuo + tooltip "fuera de
  Repetidores Sierra") en vez de ocultarse o forzar cambio de sitio —
  confirmado por el usuario que Focus debe poder salirse del sitio.

---

## 7. Estadísticas del sitio

Panel propio, visible con un sitio activo (StatusPanel del Centro, o
cabecera de Flota — mismo dato, dos superficies):

```
┌ REPETIDORES SIERRA ─────────────────────────────────────┐
│ 16/18 online (89%)          🔋 78% media (12% peor: Nodo Solar)   │
│ 📶 SNR medio: buena          🌡 18.4°C media   ⚗ 1013 hPa media   │
│ ⛭ 2/2 gateways disponibles   🔁 redundancia: 14/18 con 2+ gws     │
│ ⏱ contacto medio: 2m         ⚠ 1 alerta activa   ▶ 2 operaciones  │
└───────────────────────────────────────────────────────────┘
```

Reutilización directa: online/offline, redundancia y gateways disponibles
salen de `compute_multi_gateway_stats` (`gateway_stats.py:45-100`, ya
genérico — no asume toda la red). Batería media y tiempo medio desde último
contacto son agregados triviales sobre `NodeSummaryOut` ya disponible.
Temperatura, presión y uso de canal dependen de si el backend ya ingiere esa
telemetría ambiental — no confirmado en esta investigación, condicionado a
verificación (D2, §11). Nunca se mezclan aquí estadísticas de toda la red —
en modo "Todos" este panel es sencillamente el Dashboard actual, sin
cambios.

---

## 8. Taxonomía de tipos de nodo (sin cambios respecto a la v1)

| Categoría | Señal | Fiabilidad |
|---|---|---|
| 🛰 **Gateway** | `node_id` coincide con `gateways.local_node_id` de una fila `managed` | Dato duro (M5), requiere cruce nuevo (§10.1) |
| 📡 **Infraestructura** (router/repetidor) | `role` ∈ {ROUTER, ROUTER_CLIENT, REPEATER} | Dato duro (firmware) |
| 📍 **Nodo fijo** | Convención manual: tag `fijo` | Heurística/convención — no hay señal de firmware fiable para "no se mueve" |
| 👤 **Usuario** | `role` ∈ {CLIENT, CLIENT_MUTE, TRACKER, TAK, TAK_TRACKER} y no está en las anteriores | Dato duro como default |
| ❓ **Sin clasificar** | `role` nulo o sin mapeo claro | — |

Nombres confirmados por el usuario (coinciden con los propuestos en la v1).
La jerarquía gateway → infraestructura → fijo → usuario → sin clasificar se
fija; los nombres de visualización quedan abiertos a ajuste fino sin volver
a esta revisión.

---

## 9. Decisiones confirmadas por el usuario (cierran las preguntas de la v1)

### 9.1 Primera ejecución sin sitios: degradación elegante, sin asistentes

Si el operador no tiene ningún sitio creado, **todo funciona exactamente
igual que hoy** (v0.8): Flota es la tabla/roster actual sobre toda la red,
sin bloques ni taxonomía, sin banner ni modal de "crea tu primer sitio". El
selector del HUD muestra únicamente "🌐 Todos los nodos (N)" con la opción
discreta "+ Crear sitio…" — visible, nunca forzada. El producto no empuja al
operador hacia el nuevo modelo; se descubre solo cuando el propio operador
crea su primer sitio.

### 9.2 Taxonomía: confirmada tal cual (§8), sin cambios.

### 9.3 Un único sitio activo — nunca varios simultáneos

Confirmado explícitamente: el objetivo es reducir ruido, y permitir varios
sitios activos a la vez reintroduciría exactamente el ruido que se quiere
eliminar. El modelo de estado se mantiene simple:
`activeSiteId: string | null` (nunca un array). Comparar sitios entre sí
queda anotado como una funcionalidad **distinta y futura** (D4, §11), no
una variante de "varios activos".

---

## 10. Compatibilidad con la arquitectura existente

| Pieza | Estado | Detalle |
|---|---|---|
| `groups` / `group_members` | **Reutilizado sin cambios** | Migración `0004_node_organization.py:32-45`; un Sitio es solo una referencia a un `group_id` existente |
| `groups.icon` | **Nuevo, opcional, aditivo** | Única adición de esquema propuesta (§2.2); no bloquea el resto |
| Filtro por sitio | **Ya funciona hoy** | `apply_filters`, `node_filters.py:53` — `GET /nodes?group_id=X` ya filtra correctamente |
| Stats por subconjunto | **Función ya genérica** | `compute_multi_gateway_stats` (`gateway_stats.py:45-100`) no asume toda la red |
| `DashboardService` escopado | **Nuevo, aditivo** | Necesita parámetro/método `group_id` opcional; no reescribe `_compute()` |
| Focus | **Coexiste sin fusionarse** | `FocusState` sigue siendo `{id, since}` de un nodo; puede apuntar fuera del sitio (§3) |
| Selección (`checkedIds`) | **Sin cambios de modelo** | Sigue siendo `Set<node_id>`; cambia solo qué universo se ofrece para poblarla |
| BatchWizard / `create_planned` | **Sin cambios** | El motor de lotes (M2/M6) no sabe qué es un "sitio activo" — solo recibe `node_ids` |
| Tags | **Conviven, no se fusionan** | Tags = taxonomía transversal (p. ej. "fijo"); sitios = ámbito operativo |
| `NodeSummaryOut.is_gateway` | **Nuevo campo, aditivo** | No existe hoy correlación entre `gateways.local_node_id` y la lista de nodos (§10.1) |
| Grupos dinámicos (`kind`, `filter_expr`) | **Fuera de alcance de esta fase** | Columnas ya existen (M1.2) sin lógica; ver D1 en §11 |

### 10.1 El único hueco real: correlación gateway↔nodo

Hoy `GatewaysView` no cruza el `local_node_id` de una pasarela gestionada
con la lista de nodos. Para que el bloque 🛰 Gateways funcione, `NodeSummaryOut`
necesita un booleano derivado (`is_gateway` o `managed_gateway_id`) — cambio
pequeño, aditivo, sin migración (se calcula al vuelo, igual que ya se
cruzan `gateway_links` para M6.2).

---

## 11. Implementación incremental propuesta (no ejecutar todavía)

**Fase A — backend aditivo + selector sin rediseño visual** (riesgo bajo)
- A1. `NodeSummaryOut.is_gateway` (cruce con `gateways.local_node_id`).
- A2. `groups.icon` opcional (migración aditiva, nullable, sin efecto si no
  se usa).
- A3. `DashboardService` acepta `group_id` opcional, reutilizando
  `compute_multi_gateway_stats`/`compute_status` sin tocar su lógica interna.
- A4. Selector de Sitio activo en el HUD + botón `[Todos]`, persistido
  (`usePersistedState`). Flota empieza a pasar `group_id` a su fetch
  existente — **sin** rediseño de bloques todavía, solo filtro. Sin sitios
  creados, comportamiento idéntico a hoy (§9.1).

**Fase B — rediseño estructural de Flota**
- B1. Vista de bloques plegables por taxonomía (§6, §8), con contador y
  selección de bloque, activa únicamente dentro de un sitio.
- B2. Acciones de bloque completo (extensión directa de "+ visibles").

**Fase C — propagación al resto del Centro**
- C1. Mapa: `fitBounds` + atenuación de nodos fuera del sitio.
- C2. StatusPanel/KPIs escopados, con toggle "ver red completa".
- C3. Alertas/Trabajos/Actividad: filtro por defecto + badge de "fuera del
  sitio" (nunca ocultación silenciosa de CRITICAL).
- C4. Reset de selección al cambiar de sitio; distinción visual de Focus
  dentro/fuera del sitio activo.

**Fase D — evaluar tras uso real, no comprometida**
- D1. Grupos dinámicos (`kind="dynamic"`, `filter_expr`) para reducir
  mantenimiento manual en redes de cientos de nodos.
- D2. Estadísticas ambientales del sitio (temperatura/presión/canal),
  condicionado a verificar qué telemetría ambiental ya se ingiere.
- D3. Taxonomía "nodo fijo" formalizada más allá de tag manual, si la
  convención no resulta suficiente en la práctica.
- D4. Comparación entre sitios (vista lado a lado o agregada) — funcionalidad
  distinta a "varios sitios activos" (§9.3), explícitamente descartada esta
  última.

Cada fase deja el sistema funcional y aprobable de forma independiente,
siguiendo el mismo patrón incremental que v0.7 §17.

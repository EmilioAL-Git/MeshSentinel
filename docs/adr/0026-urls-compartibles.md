# ADR 0026 — URLs compartibles (deep-linking) sin router

- Estado: Aceptado (2026-07-15)
- Complementa: v0.7 §2 (principios de diseño del Centro de Operaciones),
  v0.8 (identidad "consola", NavRail sustituye a las pestañas)
- Diseño asociado: `docs/design/urls-compartibles.md`

## Contexto

El frontend nunca ha tenido enrutado. Fase 2A (mapa) ya lo decidió
explícitamente: "navegación por pestañas, sin router — esperar a Fase 2C".
Esa fase nunca llegó: v0.7.1 sustituyó las pestañas por un `NavRail` +
`useState<View>` en memoria, y v0.8 confirmó el concepto de "un solo
instrumento, no páginas". El resultado, verificado por inventario completo
del código (`frontend/src/App.tsx` y ~12 componentes): **todo** el estado de
navegación vive en `useState` de React o en `localStorage`
(`usePersistedState`, prefijo `noc.*`) — vista activa, nodo abierto en el
Inspector, Focus, grupo activo, filtros de Flota/Trabajos/Registro, capas y
viewport del mapa, edición abierta en Alertas, lote abierto en Trabajos.
Nada de eso sobrevive a un F5, y nada es enlazable: un operador no puede
pasarle a otro "mira este nodo con la capa de cobertura activa" ni volver a
un enlace que él mismo generó.

El usuario pidió expresamente que **cada clic, cada pantalla y cada estado**
sea compartible mediante un enlace.

`frontend/package.json` no tiene ninguna dependencia de router instalada.

## Decisión

### Sin librería de router

Con 10 vistas conocidas y sin anidamiento real (el "Centro" es una vista
única con overlays, no un árbol de rutas), una librería como
`react-router`/`wouter` añadiría una capa de abstracción (rutas anidadas,
loaders, `<Outlet/>`) que este árbol de vistas no necesita. Se opta por la
**History API nativa** (`window.history`, `URLSearchParams`,
`popstate`) envuelta en un store propio minúsculo, en el mismo estilo que
`usePersistedState` (que ya demuestra que el proyecto prefiere hooks
pequeños y explícitos a dependencias nuevas para necesidades acotadas). Si
en el futuro aparece anidamiento real (rutas con parámetros de path
múltiples, guards, etc.) se puede revisar esta decisión sin que el trabajo
de esta fase se tire: el contrato con los componentes (`useUrlView`,
`useUrlParam`) no depende de cómo se implemente por debajo.

### Forma de la URL

```
/{view}?{parámetros globales}&{parámetros con prefijo de vista}
```

- **Path = vista activa** (`/ops`, `/nodes`, `/jobs`, `/alerts`, `/profiles`,
  `/config`, `/activity`, `/gateways`, `/users`, `/login-log`, `/settings`),
  mismo vocabulario que `View`/`VIEWS` en `App.tsx`; `resolveView()` se
  reutiliza para los alias históricos (`/dashboard`, `/map`, `/operations`,
  `/batches` siguen redirigiendo). `nginx.conf` ya sirve
  `try_files $uri /index.html` — el fallback SPA para refrescar en
  cualquier ruta **ya existe**, sin tocar infraestructura.
- **Query params globales** (sin prefijo, cruzan de vista en vista porque
  representan contexto, no configuración de una vista concreta):
  `node` (nodo abierto en el Inspector), `tab` (pestaña del Inspector),
  `focus` (nodo en Focus), `group` (grupo activo — refleja
  `GroupContext`/`activeGroupId`).
- **Query params con prefijo de vista** (`nodes.*`, `jobs.*`, `activity.*`,
  `alerts.*`, `map.*`): todo lo que hoy es filtro/estado local de una vista
  concreta. El prefijo evita colisiones — por ejemplo `filters.group_id` de
  Flota (filtro puntual de tabla) es un concepto **distinto** del grupo
  activo global (`group`), y ya conviven hoy sin relación directa; sin
  prefijo un intento ingenuo de usar `?group=` para ambos los confundiría.
  El esquema completo, parámetro a parámetro, vive en
  `docs/design/urls-compartibles.md` (documento operativo, no arquitectura:
  se amplía sin nuevo ADR al añadir vistas).

### `replaceState` por defecto, `pushState` en navegación deliberada

Cada tecleo en un filtro o cada frame de `flyTo` del mapa NO debe generar una
entrada de historial (el botón "atrás" quedaría inservible). Regla: cambios
de **vista** (clic en el NavRail, ⌘K) y apertura/cierre del **Inspector**
usan `pushState` (son "iré aquí y quizá vuelva"); todo lo demás (filtros,
capas, viewport, Focus, grupo activo, pestaña del Inspector) usa
`replaceState` (afinar el estado de la vista actual, no un nuevo "lugar").

### Qué queda explícitamente FUERA de la URL

- **Selección múltiple de Flota para lotes** (`checkedIds`): puede llegar a
  cientos de ids, es de un solo uso (se arma y se ejecuta), y su valor
  compartido sería casi siempre inválido al momento de abrir el enlace
  (la flota cambia). Sigue en memoria.
- **Wizards multi-paso** (`BatchWizard`, `AddGatewayWizard`): flujos
  transitorios lanzados por una acción explícita, no "lugares" a los que
  volver. Si se abandona el enlace a mitad de wizard no hay nada coherente
  que reconstruir.
- **Paleta de comandos (⌘K)**: superficie de entrada, no un estado a
  compartir — abrir un enlace no debería abrir la paleta.
- **Buffer de actividad en memoria / paginación `before_id` en curso**: el
  scroll infinito del Registro ya tiene sus propios filtros de servidor en
  la URL (`activity.*`); la posición exacta de scroll no se comparte, igual
  que ningún visor de logs comparte "la línea exacta donde estabas".

## Consecuencias

- Compartir un enlace reproduce fielmente: la vista, el nodo abierto (y su
  pestaña), el Focus, el grupo activo, y los filtros/capas propios de esa
  vista.
- `usePersistedState` no desaparece: sigue siendo el sitio correcto para
  preferencias de puesto de trabajo que NO son parte de "lo que estoy
  mirando" (columnas visibles de Flota, posición de ventanas flotantes,
  paneles plegados, hora UTC en la barra de estado). La distinción a aplicar
  en cada caso nuevo: **¿esto describe qué le enseño a alguien, o cómo tengo
  yo montado mi puesto?** — lo primero va a la URL, lo segundo a
  `localStorage`.
- Al cargar con parámetros en la URL, estos ganan sobre `localStorage` para
  las claves que hoy usan ese hook y pasan a vivir también en la URL (p.ej.
  `activeGroupId`, capas del mapa): la URL representa una intención
  explícita de "quiero ver esto", más fuerte que la preferencia arrastrada
  de la sesión anterior. Tras la carga inicial ambos quedan sincronizados
  (se sigue escribiendo en `localStorage` para que la siguiente sesión SIN
  enlace recuerde el último estado).
- Bug preexistente encontrado durante el inventario: `MapView.tsx` pasa
  `"noc.map.layers"` a `usePersistedState` (que ya antepone `noc.`),
  produciendo la clave doble `noc.noc.map.layers`. Se corrige de paso al
  migrar ese estado a la URL (deja de pasar por esa clave).
- Trabajo futuro no incluido en esta fase: correlación de alertas,
  selección por operación de administración remota — sin relación con este
  ADR.

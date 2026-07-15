# URLs compartibles — guía de aceptación

Ver ADR 0026 y `docs/design/urls-compartibles.md` para el diseño completo.
Solo frontend, sin cambios de backend ni de contrato — nada de esta guía
requiere reconstruir el backend Docker, basta con `npm run build` (o el
dev server de Vite) en `frontend/`.

## Concepto a verificar en cada punto

Copiar la URL de la barra de direcciones en un momento dado, pegarla en
otra pestaña (o ventana de incógnito, para descartar caché/localStorage
compartido) y comprobar que la pantalla resultante es la misma que se
copió — mismo nodo abierto, mismos filtros, mismas capas, mismo grupo.

## A. Navegación básica

1. Con la app cargada en `/ops`, haz clic en "Flota" en el riel — la URL
   cambia a `/nodes`. Pulsa "atrás" del navegador: vuelve a `/ops`
   (`pushState`, no `replaceState` — cambio de vista es navegación real).
2. Refresca la página estando en `/nodes` (o cualquier vista) — la app
   carga directamente ahí, no en el Centro por defecto. Prueba también
   pegar `/dashboard` o `/map` a mano: deben resolver a `/ops` (alias
   históricos, `resolveView`).
3. Pega una URL con un path inventado, p.ej. `/qwerty` — no debe romper la
   app; cae a `/ops` (fallback de `resolveView`, endurecido en esta fase:
   antes de esto cualquier string se aceptaba sin validar).

## B. Inspector, Focus y grupo activo (piloto)

1. Abre un nodo cualquiera (clic en la tabla de Flota o en el mapa). La URL
   gana `?node=!xxxxxxxx`. Copia la URL, ábrela en una pestaña nueva: el
   Inspector se abre solo en ese nodo.
2. Dentro del Inspector, cambia de pestaña (p. ej. a "Telemetría"). La URL
   gana `&tab=telemetry`. Abrir el enlace en otra pestaña debe abrir
   directamente esa sección, no la última usada localmente.
3. Activa Focus (◎) sobre un nodo — la URL gana `&focus=!xxxxxxxx` y el
   chip de Focus aparece en la cabecera. Comparte el enlace: quien lo abre
   ve el mismo nodo enfocado (mapa atenuado salvo alertas, sección ◎ FOCUS
   en Actividad).
4. Con un grupo activo seleccionado (GroupSelector), la URL gana
   `&group=<id>`. Abre el enlace sin haber tenido nunca ese grupo activo
   localmente (o en incógnito): el grupo se activa solo con la URL, sin
   tocar `localStorage` primero.
5. Cierra sesión de grupo (✕ del GroupSelector) y recarga SIN el parámetro
   `group` en la URL: debe recuperar el último grupo activo guardado en
   `localStorage` (la preferencia de sesión sigue funcionando cuando no hay
   enlace explícito).

## C. Mapa (`/ops`)

1. Activa capas no-default (p. ej. "Malla real" + "Cobertura") y cambia el
   modo de color a "Calidad". La URL gana `map.layers=neighbors,coverage`
   (orden no importa) y `map.color=quality`. Comparte el enlace: se abren
   exactamente esas capas.
2. Desactiva una capa que viene activada por defecto (p. ej.
   "Infraestructura"). Comprueba que también queda reflejado en la URL
   (no solo las altas sobre el default, también las bajas).
3. Mueve/haz zoom en el mapa. Tras soltar el gesto (`moveend`/`zoomend`),
   la URL gana `map.lat`/`map.lng`/`map.z`. Comparte el enlace: el mapa
   abre centrado ahí, sin el encuadre automático a los nodos (que solo
   corre cuando NO hay viewport en la URL).
4. Usa "⌖ Centrar" desde el Inspector de un nodo con posición: la URL de
   viewport se actualiza al vuelo (aunque estuvieras en otra vista y haya
   navegado a `/ops`).

## D. Flota (`/nodes`)

1. Aplica varios filtros (texto + favorito + etiqueta + pasarela). La URL
   gana `nodes.q`, `nodes.favorite=1`, `nodes.tag=...`, `nodes.gw=...`.
   Comparte el enlace: la tabla abre pre-filtrada igual.
2. Con un grupo activo Y un filtro de grupo de tabla (`nodes.group`, el
   selector "Grupo" del propio panel de filtros) distintos entre sí,
   confirma que no se pisan — son parámetros distintos (`group` vs.
   `nodes.group`) y conceptos ya independientes antes de esta fase.
3. "Limpiar filtros" debe vaciar todos los `nodes.*` de la URL.

## E. Trabajos (`/jobs`)

1. Filtra por nodo/tipo/pasarela (`jobs.node`/`jobs.type`/`jobs.gw`).
2. Abre un lote desde el historial (clic para expandir la tarjeta) — la URL
   gana `jobs.batch=<id>`. Comparte el enlace: el lote llega ya expandido.
3. Lanza un lote nuevo desde el asistente (Flota → "Crear lote" →
   confirmar): al terminar, `App.tsx` navega a `/jobs` con `jobs.batch` ya
   apuntando al lote recién creado (mismo comportamiento que antes de esta
   fase, ahora también compartible).

## F. Registro (`/activity`)

1. Filtra por nodo/pasarela/categorías/tipo de paquete y escribe algo en la
   búsqueda (espera el debounce ~350 ms). La URL gana `activity.node`,
   `activity.gw`, `activity.cat` (omitido si están todas las categorías
   activas), `activity.packet`, `activity.q` — con el texto YA buscado, no
   cada pulsación de tecla.
2. Comparte el enlace mientras se está escribiendo (antes de que salte el
   debounce): el campo de búsqueda del que abre el enlace debe partir del
   último valor confirmado, no perder la búsqueda.
3. El toggle "Agrupar ráfagas" NO debe aparecer en la URL — es preferencia
   de presentación (`localStorage`), verifícalo abriendo el enlace en
   incógnito: por defecto vendrá activado igual (default `true`), no
   heredado de ningún sitio.

## G. Alertas (`/alerts`)

1. Pulsa "Ajustar" sobre una regla existente — la URL gana
   `alerts.edit=rule:<id>`. Comparte el enlace: el editor de esa regla se
   abre solo, con sus valores ACTUALES (no un borrador a medias de quien
   comparte).
2. Pulsa "+ Nueva" (regla, integración o canal) — la URL gana
   `alerts.edit=new-rule` / `new-provider` / `new-channel`. Cierra el
   modal: el parámetro desaparece de la URL.
3. Solo debe poder haber un editor abierto a la vez (abrir uno cierra
   cualquier otro) — verificado por construcción (un único parámetro
   `alerts.edit`), pero confirmar visualmente que no hay overlays dobles.

## H. Perfiles (`/profiles`)

1. Abre un perfil de la lista — la URL gana `profiles.open=<id>`. Comparte
   el enlace: se abre directamente el detalle/comparación de ese perfil.
2. Entrar en "Nueva versión" o "Crear perfil" NO debe generar un enlace
   reproducible del formulario en curso (decisión de diseño, igual que
   Alertas) — confirmar que la URL no cambia al abrir esos formularios más
   allá de mantener `profiles.open` si venías de un perfil concreto.

## I. Casos límite

1. Editar la URL a mano con un `node=` inexistente: el Inspector debe
   manejarlo con su estado de carga/error habitual (la query de React Query
   falla o devuelve vacío), sin romper el resto de la pantalla.
2. Editar `group=` a un id de grupo borrado: mismo criterio que ya regía
   `activeGroupId` antes de esta fase (grupo no encontrado ⇒ sin grupo
   activo efectivo).
3. Navegar con los botones atrás/adelante del navegador repetidamente entre
   vistas y nodos abiertos — no debe haber parpadeos ni pérdida del estado
   de las queries (TanStack Query cachea por `queryKey`, no por URL).

## No incluido en esta fase (confirmar que sigue así)

- Selección múltiple de Flota para lotes, apertura de los asistentes
  (`BatchWizard`, `AddGatewayWizard`), la paleta ⌘K, y la posición de
  scroll del Registro NO deben aparecer nunca en la URL — son
  deliberadamente efímeros (ver ADR 0026).
- `/config` (edición de configuración de un nodo) y `/gateways`
  (tarjetas expandidas) siguen sin parámetros propios en esta fase —
  motivo documentado en `docs/design/urls-compartibles.md` §3.7.

# Roadmap — decisiones anotadas para después de la v0.7

Decisiones ya tomadas con el usuario que NO deben implementarse hasta
cerrar la v0.7 (Centro de Operaciones). Anotadas aquí para no perderlas y
para que las fases actuales las preparen sin adelantarse.

## 1. Selección de gateway para administración remota (Multi-Gateway)

**La siguiente mejora funcional importante del Multi-Gateway.** Decisión
del usuario (2026-07-10, al cerrar la arquitectura de transportes
USB/TCP/Simulado tras M6.2 y ADR 0023).

Política definitiva de resolución de pasarela al encolar una operación,
por orden de precedencia:

1. **Override de la operación** — el operador elige pasarela solo para esa
   operación (aprovecha `target_gateway_id`, ya presente en
   `RemoteFlagPlanItem` desde M4.2 y en el enrutado de M6.2).
2. **Gateway preferido del nodo** — persistente (`preferred_gateway_id`,
   columna nueva en `nodes`): infraestructura fija donde un nodo siempre
   lo gestiona la misma pasarela.
3. **Ranking automático** — prioridad → saltos → SNR → RSSI → recencia
   (hoy el enrutado de M6.2 usa `select_primary_link`; se ampliará a este
   ranking completo; la columna `gateways.priority` existe desde M5
   reservada exactamente para esto).
4. **Política de fallback configurable** — qué hacer si la elegida no está
   operativa (hoy: fallback fijo a `nodes.gateway_id`, sin failover).

Caso de uso: un nodo tiene gateway preferido porque normalmente siempre lo
gestiona el mismo (instalación fija), pero el operador lo sobrescribe para
una operación concreta cuando quiere probar otra pasarela.

Preparación permitida durante v0.7 (sin implementar): dejar hueco visual
en el Inspector (sección de pasarelas por nodo) para marcar la preferida.

## 2. Traceroute activo como herramienta de DIBUJADO de la red real

> **Actualización 2026-10-05**: puntos 1–2 (persistir trazas + grafo acumulado
> por API) implementados, ADR 0031. Pendientes: 3 (dibujado), 4 (barrido), 5, 6.

**Decisión del usuario (2026-10-03): implementarlo más adelante, NO ahora.**
Motivo: el traceroute activo (`traceroute.run`, ya operativo y probado con
hardware real: X1 → T1000 directo, SNR 14,5 dB ida / 16 dB vuelta) es la única
fuente de topología REAL de caminos que tiene el sistema. El observador pasivo
solo oye tráfico dirigido a su propio nodo y NeighborInfo (si el firmware lo
emite); el traceroute da la ruta efectiva y el SNR de cada salto, ida y vuelta.

Hoy cada traceroute solo se ve como un toast, una entrada del Registro y, si
llegó la respuesta, una ruta suelta en la capa «Rutas» del mapa. La idea es
convertirlo en un **mapa de la red construido a base de trazas**:

1. **Persistir las trazas** (tabla append-only `node_traces`: origen = pasarela,
   destino, ruta ida/vuelta, SNR por salto, hop_limit, fecha) — hoy el
   resultado solo vive en `admin_operations.result` y en `activity_log`.
2. **Grafo acumulado**: unir las trazas en aristas nodo↔nodo con SNR medio,
   última vez vista y nº de observaciones; fusionar con `node_neighbors`
   (NeighborInfo) marcando el origen del dato (traza activa vs. vecino pasivo).
3. **Dibujado**: capa del mapa «Red real» (grosor/color por calidad del
   enlace, antigüedad atenuada) y vista de **grafo/topología** independiente
   de las posiciones (útil con nodos sin GPS).
4. **Barrido guiado**: lanzar trazas a un grupo o a toda la flota con
   presupuesto de airtime (secuencial, espaciado, sin lotes ciegos: el
   registro marca `allow_bulk=False` a propósito; haría falta un planificador
   propio con límite por minuto y por pasarela) y trazas periódicas de
   «nodos ancla» para mantener el dibujo vivo.
5. **Derivados**: nodos puente/puntos únicos de fallo (articulación del grafo),
   nodos huérfanos, saltos máximos reales por nodo, caminos alternativos,
   degradación de un enlace en el tiempo → alertas (`neighbor_link_lost`
   ya existe para vecinos; análogo para trazas).
6. **Multi-gateway**: la traza sale por la pasarela que resuelve el enrutado de
   siempre; con 2+ pasarelas se pueden comparar caminos desde cada una.

Límites a tener presentes: cada traza inunda la malla hasta `hop_limit`
saltos (airtime real en EU_868), el firmware limita la frecuencia de
traceroutes por nodo, y una traza sin respuesta es un resultado, no un error
(no reintentar). Requiere ADR (modelo de datos nuevo + planificador).

## 3. Mapa 3D general: siguientes herramientas (anotado 2026-10-05)

El Mapa 3D ya es un mapa general (nodos + búsqueda → trazas del nodo) con
Perfil topográfico (línea de visión) entre dos puntos. Ideas pendientes, sin implementar:

1. **Viewshed de un nodo**: zona visible desde un nodo con su mástil, sobre el DEM
   (también para un punto planeado: dónde colocar un nodo nuevo).
2. **Mejor sitio intermedio** para desbloquear un enlace obstruido (parte del perfil).
3. **Enlaces probables vs reales**: perfil automático de pares cercanos contrastado
   con vecinos/trazas reales (enlaces que deberían existir y no están, y al revés).
4. **Capa «Red real» en 3D** (grafo acumulado de trazas, ver §2).
5. **Capas de la malla en 3D**: cobertura por pasarela, vecinos, calidad de señal.
6. **Historial temporal**: reproducir un nodo móvil o la evolución de la cobertura.
7. **Medida y exportación**: regla (distancia/azimut), captura, perfil a PNG/CSV.
8. **Comparador de trazas** (dos trazas al mismo destino superpuestas).

Recomendación dada al usuario: empezar por 1 y 3 (reutilizan `elevation.ts`).

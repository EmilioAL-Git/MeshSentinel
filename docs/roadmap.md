# Roadmap — lo pendiente

Lo planeado pero aún no implementado, con las decisiones ya tomadas con el
usuario. Lo ya hecho se anota en cada sección como contexto; el estado
módulo a módulo está en `docs/status.md`. Última revisión: 2026-10-06.

## 1. Selección de gateway para administración remota (Multi-Gateway)

> **Actualización 2026-10-06: implementado casi por completo.** El resolver de
> pasarela al encolar (`application/admin/gateway_routing.py`, migración 0010)
> aplica los niveles 1–3: override por operación, `nodes.preferred_gateway_id`
> y ranking prioridad → saltos → SNR → RSSI → recencia sobre los enlaces N:M
> (`select_primary_link`). Las pasarelas de solo recepción y las eliminadas o
> deshabilitadas quedan fuera de los candidatos. El preview de lotes usa el
> mismo resolver.

**Pendiente:**

- **Política de fallback configurable** (nivel 4): hoy, sin candidato válido,
  el fallback es fijo a `nodes.gateway_id` (solo si esa pasarela está
  operativa-pero-caída o sin fila; nunca una retirada).
- **Failover automático** tras fijarse la pasarela de una operación: descartado
  a propósito (ADR 0013: evitar doble ejecución sobre LoRa); el reintento
  manual re-evalúa.
- **Límite de tasa de administración por pasarela**: hoy `admin_rate_limit_per_minute`
  es global entre todas las pasarelas (el «1 en vuelo» sí es por pasarela).

## 2. Traceroute activo como herramienta de DIBUJADO de la red real

> **Actualización 2026-10-06**: puntos 1–2 (persistir trazas + grafo acumulado
> por API) implementados, ADR 0031; el historial de trazas y el Mapa 3D de una
> traza ya existen (Herramientas), y la capa «Malla real» del mapa pinta
> NeighborInfo. Pendientes: 3 (dibujado del grafo acumulado y vista de
> topología), 4 (barrido guiado), 5 (derivados) y 6 (comparar pasarelas).

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
Perfil topográfico (línea de visión) entre dos puntos, y existe la herramienta
**Calculador de cobertura 3D** (estimación de alcance de un emisor sobre el
relieve: espacio libre + difracción Bullington; no es un simulador RF). Ideas
pendientes, sin implementar:

1. **Viewshed de un nodo** (distinto del calculador de cobertura, que modela
   potencia, no solo visibilidad): zona visible desde un nodo con su mástil, sobre el DEM
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

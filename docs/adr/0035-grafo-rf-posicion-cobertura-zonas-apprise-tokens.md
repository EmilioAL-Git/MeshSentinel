# ADR 0035 — Grafo RF, posición estimada, cobertura medida, zonas, Apprise y tokens de API

Estado: aceptada (2026-10-06). Origen: `docs/research/meshmonitor-comparativa.md` (3.3 fases 2, 3.4, 3.6,
3.8, 3.10 y 3.11). Migraciones 0034, 0035 y 0036. Todo pasivo (nada se transmite por la malla).

## 1. Informe de problemas, fase 2 (grafo RF)

`application/rf_graph.py` (puro) construye un grafo de enlaces **dirigidos** (transmisor → receptor, SNR
medido en el receptor) con dos fuentes: NeighborInfo (`node_neighbors`) y saltos de traza
(`node_trace_hops`). Reglas nuevas (umbral editable): `asymmetric_link` (SNR distinto > 6 dB según el
sentido; sujeto = el extremo que oye peor), `router_cluster` (router enlazado con ≥ 3 routers;
ROUTER_LATE excluido a propósito), `hop_horizon` (nodo activo a ≥ 7 saltos) y `router_moving`
(router/repetidor que abarca > 1 km en 24 h; caja envolvente de posiciones).

**Límite honesto:** en la malla real `node_neighbors` está vacío (nadie tiene NeighborInfo activado) y
solo hay 9 trazas, así que las dos reglas de grafo no disparan hoy — se probaron con datos sintéticos y
quedan listas. `hop_horizon` sí tiene datos (6 alertas reales). Para que el grafo sirva hay que activar
NeighborInfo en algunos routers.

## 2. Posición estimada para nodos sin GPS

Tabla `estimated_positions` (estado derivado, una fila por nodo, reemplazada cada hora por
`PositionEstimationService`). `application/position_estimate.py` (puro): centroide ponderado (SNR y
antigüedad) con radio de incertidumbre (5 km con un ancla, menos con varias convergentes; sin
estimación si las anclas están a más de 10 km entre sí). **Anclas válidas solo si acotan la distancia
por alcance de radio**: pasarela que lo oyó a 0 saltos (posición del nodo local de la pasarela) y
enlaces de vecinos/trazas con nodos posicionados. Un nodo oído a ≥ 1 salto no ancla nada. Prioridad
real > manual > estimada (la capa del mapa no pinta nodos con GPS). Procedencia siempre «inferida».
**Límite honesto:** con la malla real salen 2 estimaciones — casi todos los nodos sin GPS los oyen las
pasarelas a 3-5 saltos.

## 3. Cobertura medida

Tabla `coverage_receptions` (append-only, retención `retention_coverage_days` = 90): se registra una
fila por **posición oída a 0 saltos** con SNR y precisión ≥ 16 bits (≈ 720 m; una posición difuminada
no mide nada). «A 0 saltos» se toma del enlace nodo↔pasarela (último `hops_away`), porque el evento de
posición no lleva saltos — decisión para no tocar el contrato ni obligar a recrear gateways. `GET
/coverage` agrega por celda de ~110 m **en Python**: `round(double, int)` en SQL no es portable
(PostgreSQL solo lo admite sobre `numeric`) y rompió en producción un primer intento que solo se había
probado en SQLite. Capa «Cobertura medida» del mapa. Solo mide donde hubo un nodo con GPS emitiendo:
ausencia de celda ≠ ausencia de cobertura.

## 4. Zonas (geofence), parte pasiva

Dos tipos de regla basados en estado: `geofence_inside` (dispara mientras el nodo está dentro; se
resuelve al salir) y `geofence_outside` (dispara mientras está fuera). Zona circular: centro en `params`
{lat, lon}, radio en `threshold` (m); validado en la API. Exige nodo online y posición de ≤ 6 h. Sin
siembra por defecto (la zona solo la conoce el operador) y la acción es solo notificar.

## 5. Apprise

Proveedor `apprise`: cliente HTTP de un servidor Apprise API (`POST {url}/notify/{key}` o modo sin
estado `POST {url}/notify` con `urls`); da acceso a 100+ servicios sin dependencias nuevas. Tipo
info/warning/failure según severidad, success al resolver.

## 6. Tokens Bearer de API

Tabla `api_tokens` (solo hash SHA-256; valor en claro `msk_…` mostrado una vez). `get_current_user`
acepta `Authorization: Bearer`; un Bearer **inválido es 401 y no cae a la cookie**. El token actúa con
su rol (`manager`/`user`, **nunca admin**), no tiene espacio personal (favoritos/grupo → 403) y su actor
queda como `token:<nombre>`. Gestionarlos exige **admin con sesión real incluso en modo abierto**: un
token creado sin sesión sobreviviría al arranque del modo protegido (escalada). UI: Usuarios → Tokens de
API. Documentación OpenAPI en `/api/v1/docs`.

## No hecho

Alerta de `heapFreeBytes`: no se decodifica `LocalStats` (haría falta decoder + contrato + columna +
migración; no era barata). Detección de suplantación (3.7): beneficio bajo con el filtro actual.

# Guía de aceptación — Mapa como centro operativo

Objetivo: comprobar las capas nuevas del mapa (Traza, Rutas, Malla real,
Cobertura, flujo de tráfico) y la infraestructura de topología que las
alimenta (tabla `node_neighbors`, `GET /topology`,
`GET /nodes/{id}/neighbors`, filtro `internal_type` en `GET /activity`).
Referencias: `docs/design/motor-de-reglas-y-topologia.md` §2 (diseño
implementado), migraciones 0013/0014.

> **Requisito de datos**: "Malla real" y el detalle de vecinos solo pintan
> si algún nodo de la malla tiene el módulo **NeighborInfo activado por
> firmware** (no es el default en todas las versiones). "Rutas" solo pinta
> traceroutes que la pasarela haya recibido — y una pasarela solo recibe
> los dirigidos a su propio nodo (los traceroutes entre nodos terceros son
> invisibles para un observador pasivo, ver operator-notes). Sin esos
> datos, ambas capas quedan vacías: comportamiento esperado, no un bug.

## 0. Preparación

Backend en Docker necesita rebuild (migraciones 0013/0014 corren solas en el
entrypoint):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d postgres redis backend frontend
```

El simulador NO genera NeighborInfo/traceroute. Dos opciones:

- **Hardware real** (la validación que importa): malla con NeighborInfo
  activado en al menos un nodo, y lanzar un traceroute desde la app oficial
  hacia el nodo local de la pasarela.
- **Eventos sintéticos** (humo rápido, sustituir los node_id por los reales
  de tu BD — deben tener posición para que el mapa pinte):

```bash
docker compose exec redis redis-cli PUBLISH noc:events '{"schema_version":1,"event_type":"neighbors.seen","event_id":"<uuid>","gateway_id":"gw-01","timestamp":"<iso-utc>","payload":{"node_id":"!aaaaaaaa","neighbors":[{"neighbor_id":"!bbbbbbbb","snr":5.5}],"snr":3.0,"rssi":-70}}'
```

## 1. Infraestructura de topología (API)

1. `curl localhost:8000/api/v1/topology` → un enlace por par
   `(node_id, neighbor_id)`, con `active` según el umbral de offline.
   Repetir el mismo `neighbors.seen` dos veces con SNR distinto: sigue
   habiendo UN enlace por par, con el SNR del último.
2. `?since_hours=1` acota la ventana; el default es 24 h (un par oído una
   sola vez desaparece de la capa al día siguiente, aunque la tabla lo
   conserve — append-only).
3. `curl localhost:8000/api/v1/nodes/!aaaaaaaa/neighbors` → vecindario
   ACTUAL: un enlace por vecino, sin duplicados aunque haya N paquetes.
4. `curl "localhost:8000/api/v1/activity?internal_type=TRACEROUTE_APP"` →
   solo entradas de traceroute, con `payload.raw.route` intacto.

## 2. Capas del mapa (Centro)

En el panel de capas (esquina superior derecha del mapa):

- **⌁ Malla real**: líneas punteadas nodo↔nodo coloreadas por SNR
  (verde ≥0 dB, ámbar <0, rojo <−12; gris = enlace fuera del umbral de
  offline). Un par que se oye mutuamente dibuja UNA sola línea.
- **🧭 Rutas**: trazo amarillo del último traceroute — origen = nodo local
  de la pasarela que lo recibió, saltos intermedios, destino. Se desvanece
  con la edad (opaco <30 s, tenue <2 min, residual después).
- **〜 Traza**: con un nodo en Focus (◎) o abierto en el Inspector, su
  recorrido GPS reciente como línea discontinua con puntos. Sin nodo
  activo, la capa no pinta nada.
- **◌ Cobertura**: polígono/círculo translúcido por pasarela envolviendo
  sus nodos con enlace activo. Es una aproximación geométrica, NO un
  modelo de propagación RF — así está rotulado en el tooltip del botón.
- **Flujo de tráfico**: con "Malla real" poblada, un evento de actividad de
  un nodo con vecinos conocidos pulsa también sobre el punto medio de sus
  enlaces (además del pulso en el propio nodo, v0.7.3).
- Los toggles persisten al recargar (localStorage `noc.map.layers`).

## 3. Regresión

- El Registro sigue narrando "Información de vecinos"/"Traceroute" como
  antes (la persistencia se añadió SIN tocar la narración).
- Capa "Enlaces" (nodo↔pasarela, v0.9 Fase B) intacta e independiente.
- `pytest backend/tests gateway/tests` → todo verde (SQLite; con
  `NOC_TEST_DATABASE_URL` también en PostgreSQL).

# ADR 0031 — Trazas de la red real (traceroute como fuente de topología)

Estado: aceptado (2026-10-05). Implementa `docs/roadmap.md` §2, puntos 1–2.

## Contexto
El traceroute es la única fuente de caminos REALES (con SNR por salto, ida y
vuelta). Hasta ahora solo vivía en `admin_operations.result` (toast) y en
`activity_log` (Registro): sin estructura consultable ni acumulación.

## Decisión
1. **Dos vías, un mismo dato.** Pasiva: todo `TRACEROUTE_APP` que la API de la
   pasarela entrega (respuestas a nuestros traceroutes y paquetes dirigidos a
   su nodo local). Activa: resultado de `traceroute.run`, incluido «sin
   respuesta» (evidencia negativa, sin aristas).
2. **Contrato v1 aditivo** (`traceroute.completed`): `to_node_id`, `is_reply`,
   `route_back`, `snr_back`; `snr_towards` pasa a dB (antes cuartos de dB crudos).
   El decoder orienta: en una respuesta el emisor es el DESTINO de la traza.
3. **Modelo** (migración 0031, append-only, sin FK a `nodes` — los intermedios
   pueden ser nodos aún desconocidos): `node_traces` (una fila por traza física,
   JSON de rutas/SNR) y `node_trace_hops` (una arista dirigida por salto,
   desnormalizada para agregar el grafo con GROUP BY portable PG/SQLite).
4. **Fusión activa↔pasiva.** Un traceroute activo produce a la vez el
   resultado y el paquete de respuesta, en orden no garantizado. `record()`
   los fusiona (misma pasarela/origen/destino, ±90 s, uno con `operation_id`
   y otro `from_packet`) para contar UNA traza. Dos trazas pasivas nunca se
   fusionan entre sí.
5. **Saltos desconocidos** (`!ffffffff`) y SNR ausente (−128) no producen
   aristas falsas; el resto de la traza se conserva.
6. **API** de solo lectura: `GET /traces`, `GET /traces/graph` (arista dirigida
   agregada: observaciones, SNR medio/mín/máx/último, primera/última vez).
7. **Retención**: `retention_traces_days` (180).

## Límites asumidos
- Una pasarela solo oye trazas dirigidas a su nodo: el volumen pasivo depende
  de que alguien traceroutee a los nodos locales; el resto del grafo se
  construye con trazas activas (barrido con presupuesto de airtime: pendiente,
  roadmap §2.4).
- Orientación de una petición sin `to_node_id` asume el nodo local de la pasarela.
- Borrar un nodo no borra sus trazas (se podan por antigüedad).

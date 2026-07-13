# ADR 0011 — Dashboard NOC: agregación en backend con caché TTL y umbrales configurables

- Estado: Aceptado (2026-06-12)
- **Nota (actualizada)**: la decisión de agregación en backend/caché TTL/
  umbrales sigue exactamente vigente y en uso. Lo que sí cambió es la UI: la
  pestaña "Dashboard" independiente fue degradada a opción de menú en
  v0.7.1 y **eliminada por completo** en v0.8.0 — el endpoint
  `/dashboard/summary` alimenta hoy el panel de situación del **Centro**,
  no una vista propia. Ver `docs/status.md`.

## Contexto

El Dashboard debe permitir evaluar la red en <5 s, actualizarse por WebSocket y
seguir fluido con cientos de nodos, sin que varios operadores mirándolo a la vez
multipliquen la carga.

## Decisión

1. **Agregación íntegra en el backend**, expuesta en un único endpoint
   `GET /api/v1/dashboard/summary` que incluye también los **umbrales
   configurados** — el frontend no duplica reglas de negocio ni hace múltiples
   consultas.
2. **Reparto SQL/memoria**: SQL para últimos-valores-por-nodo (funciones de
   ventana ya existentes) y COUNTs indexados de la última hora; Python para
   porcentajes, medias, estado global y nodos críticos (≤ cientos de filas).
   "Eventos última hora" se aproxima con telemetría+posiciones persistidas
   (los node.seen no se almacenan como serie).
3. **Caché TTL en proceso (5 s, configurable)** con lock: N clientes = 1 cómputo
   por ventana. Cálculo bajo demanda, sin jobs en background.
4. **Reglas HEALTHY/WARNING/CRITICAL en función pura** (`compute_status`),
   testeada unitariamente. Umbrales por env: `LOW_BATTERY_THRESHOLD`,
   `OFFLINE_MINUTES_WARNING`, `OFFLINE_PERCENT_WARNING`,
   `OFFLINE_PERCENT_CRITICAL`, `SNR_DEGRADED_THRESHOLD` (también con prefijo
   `NOC_`).
5. **Feed de actividad 100% en cliente**: se alimenta de los eventos WS ya
   recibidos, buffer circular (25) volcado al estado máx. 1 vez/s, con dedupe
   de heartbeats consecutivos. Cero peticiones HTTP y cero almacenamiento.
6. El Dashboard es la **vista por defecto** de la aplicación.

## Consecuencias

- Sin migraciones: todo deriva de las tablas de la Fase 1.
- La caché TTL introduce hasta 5 s de retraso aceptado en los agregados;
  el feed de actividad sí es tiempo real.
- Cuando exista el motor de alertas (Fase 3C), reutilizará los mismos umbrales
  de configuración como punto de partida.

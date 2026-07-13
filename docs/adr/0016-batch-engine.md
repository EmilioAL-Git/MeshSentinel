# ADR 0016 — Batch Engine (M2): coordinación de lotes sobre el pipeline existente

- Estado: Aceptado (2026-07-09)
- **Nota (actualizada)**: la decisión de coordinación (una `AdminOperation`
  por nodo, cero efectos propios) sigue vigente. La pestaña "Batches"
  mencionada en este ADR ya no existe: se fusionó con "Operaciones" en la
  vista **Trabajos** (v0.7.4), luego re-cromada en v0.8.0. Ver
  `docs/glossary.md`.
- Complementa: ADR 0013 (pipeline), ADR 0014 (verify), diseño del Módulo 1 §4.1/§5

## Contexto

M2 exige ejecutar cualquier operación admisible sobre decenas/cientos de nodos
con control, auditoría y sin duplicar el mecanismo de ejecución.

## Decisión

1. **El Batch Engine no ejecuta nada**: crea una `AdminOperation` por nodo con
   `batch_id` y delega TODO (cola, rate limit global, 1-en-vuelo por gateway,
   verify, reintentos, watchdog, auditoría) en el pipeline de ADR 0013. Los
   únicos toques al pipeline son: (a) `next_dispatchable` no despacha
   operaciones de lotes en pausa; (b) el tracker notifica al BatchService en
   cada transición terminal para detectar la finalización del lote (misma
   transacción).
2. **Alcance congelado**: la simulación resuelve filtros/grupos/favoritos a una
   lista concreta de node_ids; el lote se crea con esa lista (snapshot
   auditado: el filtro puede dar otro resultado mañana). `scope_description`
   conserva cómo se seleccionó.
3. **Simulación sin efectos** (`preview`): advierte de nodos sin conexión
   reciente (probable timeout), bloquea desconocidos/no enrutables, marca si la
   operación exige verificación, y estima duración por el presupuesto de malla
   (`ops × 60 / rate_limit`): con LoRa el rate limit domina cualquier otra
   variable — la ETA es honesta por diseño.
4. **Estados del lote**: `running | paused | cancelled | completed |
   completed_with_errors`. `completed_with_errors` si alguna operación terminó
   failed/timeout/verify_failed. La **cancelación solo toca `pending`**: una
   operación `queued` ya viaja hacia el gateway y una `running` está sobre
   LoRa — ninguna se interrumpe; sus resultados se procesan y auditan con
   normalidad y el lote (ya `cancelled`) cierra `finished_at` cuando terminan.
5. **Sin bulk para `owner.set`** (nombres únicos por nodo); el resto de SETs y
   todos los GETs son masivos (`allow_bulk` en el registro de capacidades es
   la única fuente de esa decisión).
6. **Progreso derivado, no denormalizado**: los contadores se calculan con un
   `GROUP BY status` sobre el índice `batch_id` — nada que mantener
   sincronizado; escala a miles de operaciones por lote. ETA dinámica por
   velocidad real observada (done/elapsed) con fallback al presupuesto.

## Consecuencias

- Un lote de cientos de nodos tarda horas *por diseño* (presupuesto de malla);
  la UI muestra ETA/velocidad y sobrevive a reinicios del backend (todo el
  estado vive en BD).
- Pausar es instantáneo (no se despacha nada nuevo) y no pierde trabajo.
- El monitor reutiliza los eventos `admin.operation` existentes por WebSocket:
  cero cambios de contrato.

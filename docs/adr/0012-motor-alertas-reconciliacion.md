# ADR 0012 — Motor de alertas: reconciliación de condiciones y máquina de estados

- Estado: Aceptado (2026-07-08)

## Contexto

El motor de alertas será una pieza central del NOC durante años: debe crecer
(nuevos tipos de regla, nuevos canales, disparo por eventos, correlación,
escalado) sin rediseño. Requisito explícito: máximo desacoplamiento.

## Decisión

1. **Moneda de cambio = `AlertCondition`** (regla, sujeto, mensaje): cualquier
   fuente produce condiciones y el motor las **reconcilia** contra las alertas
   activas (`reconcile_rule`): condición nueva → `fired`; condición desaparecida
   → `resolved`; condición persistente → sin ruido (recordatorio opcional por
   `cooldown_seconds`). Deduplicación por `(rule_id, subject_type, subject_id)`.
   - Hoy la única fuente es el **evaluador periódico** (30 s, configurable con
     `NOC_ALERT_EVAL_INTERVAL_SECONDS`); mañana un manejador de eventos (USB
     desconectado, Redis caído...) llamará a `reconcile_rule` con la misma
     semántica sin tocar el motor.
2. **Evaluadores como funciones puras registradas** por `rule_type`
   (`EVALUATORS`): añadir un tipo de regla = registrar una función.
3. **Máquina de estados** `firing → acknowledged → resolved` desde el esquema
   (columnas `acknowledged_at/by`, endpoint `POST /alerts/{id}/ack`), aunque la
   UI inicial solo muestre firing/resolved. Una alerta reconocida no recibe
   recordatorios y se resuelve sola cuando la condición desaparece.
4. **Reglas en BD** con columnas comunes consultables (`severity`, `threshold`,
   `duration_seconds`, `cooldown_seconds`) y `params` JSON solo para extras por
   tipo. La severidad (INFO/WARNING/CRITICAL) se define en la regla y se propaga
   a la alerta y a los canales (p. ej. prioridad ntfy). Se siembran 4 reglas por
   defecto desde los umbrales del Dashboard si la tabla está vacía.
5. **`correlation_key`** en el esquema desde ahora (sin lógica de agrupación
   todavía); el evaluador de pasarelas ya la rellena (`gateway:<id>`).
6. **Salida por listeners inyectados** (`AlertTransition`): notificador de
   canales y difusor WebSocket son listeners; el motor no conoce HTTP, Redis ni
   FastAPI. Canales en BD gestionables por API/UI, registro extensible
   `CHANNEL_TYPES` (webhook y ntfy hoy; Telegram/email/Discord = un adapter).

## Consecuencias

- Un canal caído o un listener que falla nunca detiene la evaluación.
- Los eventos `alert.fired/resolved` del WebSocket son de origen backend y no
  forman parte del contrato gateway↔backend v1 (que permanece intacto).
- La correlación y el escalado futuros son cambios aditivos (rellenar
  `correlation_key`, nuevos listeners), no rediseños.

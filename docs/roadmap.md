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

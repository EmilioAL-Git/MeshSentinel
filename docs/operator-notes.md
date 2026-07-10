# Diario de operador

No es documentación técnica: es un registro de fricciones de uso real
detectadas mientras se implementa o se opera el NOC. Cada entrada documenta
algo incómodo, lento o poco claro para un operador — no hace falta
resolverlo al anotarlo. La UX evoluciona con el uso (v0.7, principio 8).

Formato: fecha · contexto · observación · (opcional) idea de mejora.

---

## 2026-07-10 — durante la implementación de v0.7.0

- **Las pestañas Operaciones y Batches obligan a saltar para seguir una
  misma acción.** Al cablear el segmento `▶` de la barra inferior quedó
  claro que "qué está pasando con mi lote" requiere una vista y "qué pasó
  con sus operaciones" otra. Ya decidido en diseño (§13, fusión en
  Trabajos, v0.7.4) — anotado aquí porque la fricción es real ya.

- **`succeeded_unconfirmed` como texto de chip es jerga de contrato.** El
  chip de la vista Operaciones muestra el estado crudo del backend; el
  operador tiene que conocer ADR 0019 para interpretarlo. El tooltip ayuda
  pero el literal asusta. Idea: vocabulario de operador también en la vista
  general ("confirmada por lectura" / "aceptada sin verificar"), sin perder
  el estado técnico en el detalle.

- **El HUD muestra "…" hasta que cargan las queries (2-3 s en frío).** No
  es un fallo, pero en la apertura de turno los primeros segundos el shell
  no responde aún a "¿la red está bien?". Idea futura: cachear el último
  resumen en localStorage y pintarlo atenuado como "dato de la última
  sesión" hasta que llegue el fresco.

- **La cola (`⧗`) de la barra inferior cuenta pending+queued de las últimas
  200 operaciones.** Si la cola real superara 200 (lote enorme), el número
  se quedaría corto. Hoy imposible en la práctica (rate limit 60/min y
  lotes pequeños), pero cuando exista la vista Trabajos convendría un
  endpoint de conteos agregados en vez de contar client-side.

- **El aviso de reconexión WS no distingue "backend caído" de "solo WS
  caído".** El banner dice "reconectando" también cuando todo el backend
  está abajo (aunque la barra inferior sí lo distingue vía /health). Vale
  como está, pero el texto podría coordinarse cuando ambos fallan.

- **El reloj de la barra muestra HH:MM sin segundos.** Para correlar con
  logs (uno de sus propósitos declarados, §11.2) los segundos ayudarían;
  se dejó en minutos para no tener un tick por segundo. Revisar si algún
  flujo real los echa de menos.

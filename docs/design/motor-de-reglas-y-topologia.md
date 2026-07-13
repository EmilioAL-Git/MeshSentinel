# Diseño: motor de reglas definitivo + ingesta de topología real (NeighborInfo)

> Estado: DISEÑO, sin implementar. Companion de la evolución del Centro de
> Operaciones (v0.9, Fases A–C ya implementadas). Se agrupan aquí dos
> diseños porque comparten consumidor (Situation Center y capa "Enlaces"
> del mapa) y porque el segundo es precondición de datos para completar el
> primero con una regla de "enlace nodo↔nodo perdido".
>
> **Nota (actualizada)**: parte del trabajo de decodificación que este
> documento pide en §2.2 (`decode_neighborinfo`, evento `neighbors.seen`)
> **ya aterrizó**, pero con un alcance menor al que describe este
> documento: `actividad-2.0-registro-por-paquete.md` implementó el decoder
> de `NEIGHBORINFO_APP`/`TRACEROUTE_APP`/`WAYPOINT_APP` y los eventos
> `neighbors.seen`/`traceroute.completed`/`waypoint.shared` — pero **solo
> como narración en el Registro de actividad**, no como persistencia
> consultable. La tabla `node_neighbors` y el endpoint
> `GET /nodes/{id}/neighbors` de §2 de este documento siguen sin construir;
> implementarlos ahora parte de un decoder ya existente, así que el
> esfuerzo restante es menor al que asume este documento.

## 1. Motor de reglas definitivo

### 1.1 Punto de partida

`application/alerting/evaluators.py` ya tiene la forma correcta: un
registro `EVALUATORS: dict[str, Evaluator]` por `rule_type`, funciones
puras `(AlertRule, NetworkSnapshot) -> list[AlertCondition]`, motor
(`engine.py`) que reconcilia por `correlation_key` (dedup rule+subject) y
mueve el estado firing→acknowledged→resolved. `AlertRule` (`domain/alerts/
entities.py`) ya tiene `severity`, `threshold`, `duration_seconds`,
`cooldown_seconds`, `params` (JSON, solo extras). Reglas hoy: low_battery,
node_offline, snr_degraded, gateway_disconnected. Esto NO se reescribe —
se generaliza.

### 1.2 Reglas nuevas a registrar (mismos evaluadores puros)

| rule_type | Fuente de datos (ya existe) | Umbral |
|---|---|---|
| `gateway_no_traffic` | `GatewayStats.last_heard_at` (`gateway_stats.py`) | `duration_seconds` sin oír a ningún nodo |
| `low_redundancy` | `MultiGatewayStats.redundancy_percent` | `threshold` % mínimo |
| `temperature_high` | `Telemetry.temperature_c` (device/environment) | `threshold` °C |
| `channel_utilization_high` | `Telemetry.channel_utilization` | `threshold` % |
| `position_lost` | ausencia de `Position` reciente pese a nodo online | `duration_seconds` |
| `neighbor_link_lost` | tabla `node_neighbors` (§2) — **bloqueada por §2** | enlace visto→ausente |

Todas reutilizan `NetworkSnapshot` (ampliar con `multi_gateway_stats:
MultiGatewayStats | None` y, cuando exista, `neighbors: list[NodeNeighbor]`
— aditivo, `None`/`[]` si no aplica) en vez de recalcular nada dentro del
evaluador.

### 1.3 Reglas por grupo (la decisión de modelo de datos pendiente)

Hoy toda regla es global. Para "reglas también por grupo concreto", dos
opciones:

- **A. `AlertRule.group_id: int | None`** (columna nueva, nullable):
  `None` = regla global (comportamiento actual, sin migración de datos);
  con valor, el motor evalúa esa regla SOLO sobre
  `scope_to_members(nodes, links, group.member_ids)` (`gateway_stats.py`,
  ya genérica) en vez del snapshot completo. Pros: reutiliza
  `scope_to_members`/`apply_filters` (`node_filters.py`) tal cual, cero
  concepto nuevo de dominio. Contras: una regla por grupo si se quiere el
  mismo umbral en varios grupos (aceptable, mismo patrón que perfiles M3
  — "sync" no es una regla compartida, son instancias).
- **B. Reglas globales + evaluación post-hoc por grupo** (sin columna
  nueva): el motor sigue evaluando global, y el Situation Center filtra
  `AlertCondition`/`AlertOut` por `groupNodeIds` en cliente — esto es
  **exactamente lo que ya hace** `scopeAlertsToGroup` (`GroupContext.tsx`)
  hoy. No cubre el caso "quiero un umbral de batería distinto para el
  grupo X" (ej. flota crítica con umbral más estricto).

**Recomendación**: opción A, porque el usuario ya pidió explícitamente
"reglas... tanto para toda la red como para un grupo concreto" (umbral
diferenciado, no solo el filtrado que B ya cubre). Requiere: migración
aditiva (columna nullable), `AlertRuleOut`/`AlertRuleIn` con `group_id`
opcional, UI de reglas con selector de grupo (reutiliza el selector de
grupo ya existente en `GroupContext`/`AddToGroupMenu.tsx`).

### 1.4 `correlation_key`

Ya preparada (ADR 0012) sin lógica activa. Con reglas por grupo, la clave
pasa a ser `(rule_id, group_id | None, subject_type, subject_id)` — mismo
campo, un componente más, para que la misma regla global y una variante
por grupo no se pisen si coexistieran apuntando al mismo nodo.

## 2. Ingesta de NeighborInfo (enlaces nodo↔nodo reales)

### 2.1 Por qué hace falta

La capa "Enlaces" del mapa (Fase B, ya implementada) dibuja HOY
nodo↔pasarela (`node_gateway_links`), el único enlace que el sistema
captura. El módulo `NeighborInfo` de firmware Meshtastic expone
`NEIGHBORINFO_APP`: paquetes con la lista de vecinos directos de un nodo y
el SNR hacia cada uno — la topología real de malla. Sin esto, "Enlaces"
seguirá siendo una aproximación (quién oye a quién desde la pasarela, no
quién retransmite a quién).

### 2.2 Diseño de la ingesta (paralelo exacto a Position/Telemetry)

- **Decoder** (`gateway/decoder/meshtastic.py`, único módulo que ya
  traduce paquetes de la librería oficial a eventos v1, junto con
  `gateway/decoder/admin.py`): nueva función `decode_neighborinfo(packet)
  -> dict | None` que extrae `node_id` (emisor), lista de
  `{neighbor_id, snr}` del protobuf `NeighborInfo`, y `broadcast_interval`
  si viene. Se activa solo si el paquete trae `portnum ==
  NEIGHBORINFO_APP` (mismo `if/elif` que ya distingue TELEMETRY_APP/
  POSITION_APP en el decoder actual).
- **Evento v1 aditivo** (`shared/events/`): `neighbors.seen` — mismo
  patrón que `telemetry.received`, payload `{node_id, gateway_id,
  neighbors: [{neighbor_id, snr}], received_at}`. Versión de contrato NO
  incrementa (aditivo, como `favoritos remotos` en ADR 0019).
- **Tabla append-only nueva** (migración Alembic aditiva, estilo
  `node_positions`/`node_telemetry`): `node_neighbors(id, node_id,
  neighbor_id, snr, gateway_id, received_at)`, índice en
  `(node_id, received_at)` igual que las otras dos. Append-only: "lo
  último" se resuelve con `row_number()` por `(node_id, neighbor_id)`,
  mismo principio de dominio ya documentado en CLAUDE.md.
- **Dominio**: `NodeNeighbor` (`domain/nodes/entities.py`, dataclass
  `slots=True`, mismo estilo que `NodeGatewayLink`).
- **Repositorio**: `SqlNodeNeighborRepository` (`adapters/persistence/
  repositories.py`) con `add()` y `list_latest_for_node(node_id)` —
  paralelo exacto a `SqlPositionRepository`/`SqlTelemetryRepository`.
- **Ingesta**: `IngestService.handle_event` gana un `case "neighbors.seen"`
  más (mismo `match` que ya despacha `node.seen`/`telemetry.received`/
  `position.received`), sin tocar los casos existentes.
- **API de lectura**: `GET /nodes/{id}/neighbors` (mismo patrón que
  `/positions`/`/telemetry`/`/gateways` de M6.1), y opcionalmente
  `GET /topology` de red completa (todos los enlaces vigentes) para pintar
  el mapa sin N peticiones por nodo — a decidir en implementación según
  volumen real observado.
- **Mapa**: `LinksLayer.tsx` (ya implementada, Fase B.2) gana una segunda
  fuente de enlaces (nodo↔nodo) activable como parte de la misma capa
  "Enlaces" o como una capa nueva "Enlaces (malla real)" — decisión de UX
  menor a tomar cuando haya datos reales que mostrar, no bloquea el diseño
  de ingesta.
- **Regla `neighbor_link_lost`** (§1.2): compara el último `node_neighbors`
  conocido de un par contra su ausencia en la ventana `duration_seconds`.

### 2.3 Limitaciones aceptadas

- Requiere que los nodos tengan el módulo NeighborInfo **activado por
  firmware** (no es el comportamiento por defecto en todas las versiones);
  sin él, `node_neighbors` queda vacía y la capa "Enlaces (malla real)"
  simplemente no pinta nada — nunca degrada la capa nodo↔pasarela ya
  implementada.
- Tráfico adicional en una malla de ancho de banda mínimo (duty cycle
  EU_868): el intervalo de broadcast de NeighborInfo es configurable por
  firmware, no por el NOC — el sistema es puramente observador (principio
  de dominio ya establecido), nunca fuerza su activación.
- No sustituye a `node_gateway_links`: son dos relaciones distintas
  (cobertura de pasarela vs. topología de malla) que conviven.

## 3. Orden de implementación sugerido (cuando se apruebe)

1. Migración + decoder + ingesta de NeighborInfo (§2) — infraestructura,
   sin UI todavía, validable con hardware real que tenga el módulo activo.
2. `GET /nodes/{id}/neighbors` + segunda fuente en `LinksLayer.tsx`.
3. `AlertRule.group_id` (§1.3) + reglas nuevas de §1.2 que NO dependen de
   NeighborInfo (gateway_no_traffic, low_redundancy, temperature_high,
   channel_utilization_high, position_lost) — no bloqueadas por el paso 1.
4. `neighbor_link_lost` una vez haya datos reales de producción con los
   que calibrar `duration_seconds` por defecto.

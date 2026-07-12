import type { NodeSummaryOut } from "../../api/client";

/**
 * Taxonomía de Flota (fase "Flota orientada a grupos"): SOLO tiene sentido
 * dentro de un grupo activo — nunca se clasifica "Toda la red". Usa
 * exclusivamente información ya existente hoy, sin inventar reglas ni
 * campos nuevos:
 * - Gateway: cruce con `gatewayNodeIds` (ya calculado en App.tsx desde M5,
 *   `gateways.local_node_id`) — no requiere ningún dato nuevo.
 * - Infraestructura / Usuarios: `node.role`, el rol de firmware tal cual lo
 *   reporta el propio nodo.
 * - Nodos fijos: `role ∈ {CLIENT_BASE, SENSOR}` — dos roles reales de
 *   firmware, no una heurística inventada. CLIENT_BASE es explícitamente
 *   una estación base/fija (confirmado con datos reales de esta malla:
 *   82 de 446 nodos). SENSOR se añade en esta revisión (Fase de cierre de
 *   grupos): un sensor ambiental Meshtastic es por definición un
 *   dispositivo instalado en un punto fijo — no aparece hoy en los datos
 *   reales de esta malla, pero es la misma clase de garantía semántica que
 *   CLIENT_BASE, no una suposición nueva.
 * - Sin clasificar: cualquier nodo sin señal fiable (rol nulo, o roles sin
 *   mapeo claro de operación como LOST_AND_FOUND) — nunca se adivina.
 * - TRACKER/TAK_TRACKER quedan en "Usuarios": el propio nombre del rol
 *   implica movimiento, así que NO son candidatos a "Nodos fijos" — pero
 *   tampoco son necesariamente una persona con un radio (pueden ser un
 *   vehículo o un activo rastreado). Se mantienen en el cubo "Usuarios"
 *   por ser la categoría menos incorrecta disponible, no por certeza.
 */

export type FleetCategory = "gateway" | "infra" | "fixed" | "user" | "unclassified";

export const CATEGORY_DEFS: { id: FleetCategory; icon: string; label: string }[] = [
  { id: "gateway", icon: "🛰", label: "Gateways" },
  { id: "infra", icon: "📡", label: "Infraestructura" },
  { id: "fixed", icon: "📍", label: "Nodos fijos" },
  { id: "user", icon: "👤", label: "Usuarios" },
  { id: "unclassified", icon: "❓", label: "Sin clasificar" },
];

/**
 * Clasificación manual por nodo (Inspector, Organización — `PUT
 * /nodes/{id}/node-type`): `null` = "Automático", que delega en la
 * clasificación derivada del role de firmware de siempre. Con valor, tiene
 * PRIORIDAD ABSOLUTA sobre la automática. Mismo vocabulario que
 * `FleetCategory` a propósito (backend y frontend comparten los IDs, ver
 * `NodeTypeIn` en `schemas.py`) — nunca una segunda taxonomía paralela.
 */
export const NODE_TYPE_OVERRIDE_OPTIONS: { id: FleetCategory | null; label: string }[] = [
  { id: null, label: "Automático" },
  { id: "gateway", label: "Gateway" },
  { id: "infra", label: "Infraestructura" },
  { id: "fixed", label: "Nodo fijo" },
  { id: "user", label: "Usuario" },
  { id: "unclassified", label: "Sin clasificar" },
];

const INFRA_ROLES = new Set(["ROUTER", "ROUTER_CLIENT", "REPEATER", "ROUTER_LATE"]);
const FIXED_ROLES = new Set(["CLIENT_BASE", "SENSOR"]);
const USER_ROLES = new Set(["CLIENT", "CLIENT_MUTE", "CLIENT_HIDDEN", "TRACKER", "TAK", "TAK_TRACKER"]);

function classifyByRole(node: NodeSummaryOut["node"], gatewayNodeIds: Set<string>): FleetCategory {
  if (gatewayNodeIds.has(node.node_id)) return "gateway";
  if (node.role != null && INFRA_ROLES.has(node.role)) return "infra";
  if (node.role != null && FIXED_ROLES.has(node.role)) return "fixed";
  if (node.role != null && USER_ROLES.has(node.role)) return "user";
  return "unclassified";
}

/**
 * ÚNICA función de resolución del tipo de nodo en toda la app — Flota,
 * bloques, estadísticas de grupo y cualquier clasificación futura deben
 * llamar a esta función, nunca leer `node.role`/`gatewayNodeIds` a mano.
 * Prioridad absoluta de la clasificación manual (`node_type_override`)
 * sobre la automática (derivada del role de firmware).
 */
export function classifyNode(summary: NodeSummaryOut, gatewayNodeIds: Set<string>): FleetCategory {
  const override = summary.node.node_type_override;
  if (override != null) return override as FleetCategory;
  return classifyByRole(summary.node, gatewayNodeIds);
}

export function groupByCategory(
  summaries: NodeSummaryOut[],
  gatewayNodeIds: Set<string>,
): Map<FleetCategory, NodeSummaryOut[]> {
  const map = new Map<FleetCategory, NodeSummaryOut[]>();
  for (const s of summaries) {
    const cat = classifyNode(s, gatewayNodeIds);
    const list = map.get(cat);
    if (list) list.push(s);
    else map.set(cat, [s]);
  }
  return map;
}

import type { NocEvent } from "./api/client";

export interface ActivityEntry {
  id: string;
  time: string;
  text: string;
}

export const ACTIVITY_LIMIT = 25;

export function describeEvent(event: NocEvent, nodeName: (id: string) => string): string | null {
  const p = event.payload;
  const node = typeof p.node_id === "string" ? nodeName(p.node_id) : "";
  switch (event.event_type) {
    case "node.seen":
      return `Nodo ${node} visto`;
    case "position.updated":
      return `Posición actualizada de ${node}`;
    case "telemetry.received":
      return `Telemetría recibida de ${node}`;
    case "message.received":
      return typeof p.from_node_id === "string" ? `Mensaje de ${nodeName(p.from_node_id)}` : null;
    case "gateway.status":
      return `Pasarela ${event.gateway_id}: ${String(p.status ?? "?")} (${String(p.transport ?? "?")})`;
    default:
      return null;
  }
}

export function toEntry(event: NocEvent, nodeName: (id: string) => string): ActivityEntry | null {
  const text = describeEvent(event, nodeName);
  if (!text) return null;
  return {
    id: event.event_id,
    time: new Date(event.timestamp).toLocaleTimeString(),
    text,
  };
}

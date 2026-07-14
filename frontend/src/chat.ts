import type { ActivityEntry } from "./activity";
import type { ChatMessageOut } from "./api/client";

/**
 * Chat: monitor profesional de TEXT_MESSAGE_APP, no una app de mensajería.
 * Misma naturaleza que `ActivityEntry` (un paquete = una fila), reutilizando
 * la narración que ya produce el backend para el stream en vivo — solo el
 * histórico paginado usa el endpoint dedicado `/chat/messages`.
 */
export interface ChatRow {
  /** Identidad de la fuente: `activity:<event_id>` (en vivo) o
   * `db:<chat_messages.id>` (histórico) — espacios de id distintos, nunca
   * se comparan entre sí (ver dedupe por marca de agua temporal en
   * ChatConsole). */
  id: string;
  receivedAtMs: number;
  time: string;
  fromNodeId: string;
  toNodeId: string | null;
  channelIndex: number;
  channelName: string | null;
  text: string;
  gatewayId?: string;
  rssi: number | null;
  snr: number | null;
  direction: string;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/** Deriva una fila de chat de la entrada de Actividad ya narrada — mismo
 * paquete, cero interpretación nueva. `null` si la entrada no es un mensaje. */
export function chatRowFromActivity(e: ActivityEntry): ChatRow | null {
  if (e.packetType !== "Mensaje recibido" || !e.nodeId) return null;
  const raw = e.raw ?? {};
  return {
    id: `activity:${e.id}`,
    receivedAtMs: e.receivedAtMs,
    time: e.time.slice(0, 8),
    fromNodeId: e.nodeId,
    toNodeId: typeof raw.to_node_id === "string" ? raw.to_node_id : null,
    channelIndex: typeof raw.channel_index === "number" ? raw.channel_index : 0,
    channelName: null,
    text: typeof raw.text === "string" ? raw.text : (e.description ?? "").replace(/^«|»$/g, ""),
    gatewayId: e.gatewayId,
    rssi: e.rssi ?? null,
    snr: e.snr ?? null,
    direction: "inbound",
  };
}

export function chatRowFromApi(m: ChatMessageOut): ChatRow {
  return {
    id: `db:${m.id}`,
    receivedAtMs: m.received_at ? new Date(m.received_at).getTime() : 0,
    time: m.received_at ? formatTime(m.received_at) : "",
    fromNodeId: m.from_node_id,
    toNodeId: m.to_node_id,
    channelIndex: m.channel_index,
    channelName: m.channel_name,
    text: m.text,
    gatewayId: m.gateway_id ?? undefined,
    rssi: m.rssi,
    snr: m.snr,
    direction: m.direction,
  };
}

export function channelLabel(row: Pick<ChatRow, "toNodeId" | "channelIndex" | "channelName">): string {
  if (row.toNodeId) return "Directos";
  return row.channelName ?? `Canal ${row.channelIndex}`;
}

export function initials(name: string): string {
  const clean = name.replace(/^!/, "").trim();
  if (!clean) return "??";
  const parts = clean.split(/\s+/);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return clean.slice(0, 2).toUpperCase();
}

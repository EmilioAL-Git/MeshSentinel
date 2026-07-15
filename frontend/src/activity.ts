import type { NocEvent } from "./api/client";
import { t } from "./tokens";

/** Buffer del registro de actividad (vista Registro). */
export const ACTIVITY_LIMIT = 500;

export type ActivityCategory = "operacion" | "batch" | "pasarela" | "alerta" | "malla";

export const CATEGORY_LABEL: Record<ActivityCategory, string> = {
  operacion: "Operación",
  batch: "Batch",
  pasarela: "Pasarela",
  alerta: "Alerta",
  malla: "Malla",
};

export type ActivitySeverity = "info" | "ok" | "warn" | "error";

/** Prioridad del diario operativo (Actividad 2.0 Fase 1, backend). */
export type ActivityPriority = "info" | "important" | "warning" | "critical";

export interface ActivityEntry {
  id: string;
  time: string;
  /** Epoch ms del `timestamp` del envelope — para la ventana de "último
   * minuto" (§ resumen de tráfico) y para poder ordenar/filtrar por tiempo
   * sin volver a parsear `time` (que ya viene formateado para mostrar). */
  receivedAtMs: number;
  text: string;
  category: ActivityCategory;
  severity: ActivitySeverity;
  nodeId?: string;
  /** Nombre ya resuelto por el backend ("EA2ABC"), para mostrar bajo la
   * cabecera de paquete sin repetir el node_id crudo. */
  nodeLabel?: string;
  batchId?: number;
  gatewayId?: string;
  /** Cabecera + detalles ya redactados por el backend. El frontend NUNCA
   * interpreta paquetes ni estados Meshtastic. */
  icon?: string;
  priority?: ActivityPriority;
  description?: string;
  details?: [string, string][];
  /** Capa humana de cabecera (solo entradas de paquete): "Telemetría del
   * dispositivo", "Posición actualizada"... `undefined` para sucesos no
   * derivados de un paquete concreto (gateway/alert/admin) y para los
   * hechos adicionales (reinicio, nodo nuevo, identidad). */
  packetType?: string;
  /** Capa técnica, solo visible tras expandir "Ver paquete": nunca en la
   * cabecera principal. */
  internalType?: string;
  rssi?: number;
  snr?: number;
  raw?: Record<string, unknown>;
}

const str = (v: unknown): string | undefined => (typeof v === "string" ? v : undefined);
const num = (v: unknown): number | undefined => (typeof v === "number" ? v : undefined);

/** source (backend) -> categoría de los filtros existentes. */
const SOURCE_CATEGORY: Record<string, ActivityCategory> = {
  mesh: "malla",
  gateway: "pasarela",
  alert: "alerta",
  admin: "operacion",
  system: "pasarela",
};

const PRIORITY_SEVERITY: Record<ActivityPriority, ActivitySeverity> = {
  info: "info",
  important: "ok",
  warning: "warn",
  critical: "error",
};

/** HH:MM:SS — hora exacta de recepción. Cálculo puro sobre el timestamp ya
 * provisto por el backend, sin tocar el contrato ni el modelo. */
function formatExactTime(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number, len = 2) => String(n).padStart(len, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/**
 * Identidad de tipo de paquete (pulido §3/§4): un solo mapa, clave = el
 * `packetType` que el backend ya redacta ("Telemetría del dispositivo"...).
 * Ni React ni este módulo interpretan Meshtastic — solo asocian una
 * etiqueta de filtro y un color a un texto que el backend ya decidió.
 */
export interface PacketFilter {
  key: string;
  label: string;
  /** `packetType` exactos que caen en este filtro (varios kinds de
   * telemetría comparten filtro, igual que en el resumen de tráfico). */
  types: string[];
  color: string;
}

export const PACKET_FILTERS: PacketFilter[] = [
  {
    key: "telemetria",
    label: "Telemetría",
    types: ["Telemetría del dispositivo", "Telemetría de energía"],
    color: t.catBlue,
  },
  { key: "ambiental", label: "Ambiental", types: ["Telemetría ambiental"], color: t.catGreen },
  { key: "posicion", label: "Posición", types: ["Posición actualizada"], color: t.catOrange },
  { key: "mensajes", label: "Mensajes", types: ["Mensaje recibido"], color: t.catViolet },
  { key: "nodeinfo", label: "Información del nodo", types: ["Información del nodo"], color: t.textDim },
  { key: "vecinos", label: "Vecinos", types: ["Información de vecinos"], color: t.catAqua },
  { key: "traceroute", label: "Traceroute", types: ["Traceroute"], color: t.catYellow },
  { key: "waypoint", label: "Waypoint", types: ["Waypoint compartido"], color: t.catMagenta },
];

const PACKET_TYPE_COLOR = new Map<string, string>(
  PACKET_FILTERS.flatMap((f) => f.types.map((type) => [type, f.color] as const)),
);

/** Color de identidad para una entrada de paquete; `undefined` para
 * sucesos no derivados de un paquete (gateway/alert/admin/hechos). */
export function packetColor(packetType: string | undefined): string | undefined {
  return packetType ? PACKET_TYPE_COLOR.get(packetType) : undefined;
}

/**
 * Origen/destino (pulido §1): reutiliza SOLO lo que el backend ya redactó
 * — `nodeLabel` (quién envía) y, si existe, el detalle "Destinatario" ya
 * calculado para mensajes directos. Sin ese detalle, el destino es
 * "Difusión": telemetría/posición/NodeInfo/vecinos/waypoint son, en la
 * práctica, siempre broadcast en Meshtastic — una asunción documentada,
 * no un dato leído del paquete (el contrato no lo expone hoy salvo para
 * mensajes). Ninguna interpretación de protocolo: solo texto ya decidido
 * por el backend.
 */
export function originDestination(e: ActivityEntry): { origin: string; destination: string } | null {
  if (!e.packetType || !e.nodeLabel) return null;
  const destinatario = e.details?.find(([k]) => k === "Destinatario")?.[1];
  return { origin: e.nodeLabel, destination: destinatario ?? "Difusión" };
}

/**
 * Actividad 2.0 Fase 1: el feed es el diario operativo de la red. Toda la
 * narrativa (títulos, detalles, prioridad) la produce el backend como
 * `activity.event`; los eventos técnicos (admin.operation, gateway.status,
 * node.seen…) siguen viajando por el WS para Trabajos/opTracker/queries,
 * pero ya no generan líneas propias aquí — su hecho equivalente llega ya
 * redactado desde el backend.
 */
export function toEntry(event: NocEvent): ActivityEntry | null {
  if (event.event_type !== "activity.event") return null;
  const p = event.payload;
  const source = str(p.source) ?? "system";
  const priority = (str(p.severity) ?? "info") as ActivityPriority;
  const batchId = num(p.batch_id);
  const category: ActivityCategory =
    source === "admin" && batchId != null && p.node_id == null
      ? "batch"
      : (SOURCE_CATEGORY[source] ?? "malla");
  const gatewayId = str(p.gateway_id);
  const details = Array.isArray(p.details)
    ? (p.details as unknown[])
        .filter((d): d is [string, string] => Array.isArray(d) && d.length === 2)
        .map((d) => [String(d[0]), String(d[1])] as [string, string])
    : [];
  const raw = p.raw && typeof p.raw === "object" ? (p.raw as Record<string, unknown>) : undefined;
  return {
    id: event.event_id,
    time: formatExactTime(event.timestamp),
    receivedAtMs: new Date(event.timestamp).getTime(),
    text: str(p.title) ?? "",
    category,
    severity: PRIORITY_SEVERITY[priority] ?? "info",
    nodeId: str(p.node_id),
    nodeLabel: str(p.node_label),
    batchId: batchId ?? undefined,
    gatewayId: gatewayId && gatewayId !== "system" ? gatewayId : undefined,
    icon: str(p.icon),
    priority,
    description: str(p.description),
    details,
    packetType: str(p.packet_type),
    internalType: str(p.internal_type),
    rssi: num(p.rssi),
    snr: num(p.snr),
    raw,
  };
}

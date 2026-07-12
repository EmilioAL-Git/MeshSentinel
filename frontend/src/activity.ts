import type { NocEvent } from "./api/client";

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
    time: new Date(event.timestamp).toLocaleTimeString(),
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

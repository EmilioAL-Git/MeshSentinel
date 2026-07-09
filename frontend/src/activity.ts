import type { NocEvent } from "./api/client";

/** Buffer de la consola de actividad (vista Actividad). El Dashboard muestra
 * solo las primeras entradas. */
export const ACTIVITY_LIMIT = 500;
export const DASHBOARD_ACTIVITY_LIMIT = 25;

export type ActivityCategory = "operacion" | "batch" | "pasarela" | "alerta" | "malla";

export const CATEGORY_LABEL: Record<ActivityCategory, string> = {
  operacion: "Operación",
  batch: "Batch",
  pasarela: "Pasarela",
  alerta: "Alerta",
  malla: "Malla",
};

export type ActivitySeverity = "info" | "ok" | "warn" | "error";

export interface ActivityEntry {
  id: string;
  time: string;
  text: string;
  category: ActivityCategory;
  severity: ActivitySeverity;
  nodeId?: string;
  batchId?: number;
  gatewayId?: string;
}

const str = (v: unknown): string | undefined => (typeof v === "string" ? v : undefined);
const num = (v: unknown): number | undefined => (typeof v === "number" ? v : undefined);

interface Described {
  text: string;
  category: ActivityCategory;
  severity: ActivitySeverity;
  nodeId?: string;
  batchId?: number;
  gatewayId?: string;
}

function opLabel(p: Record<string, unknown>): string {
  const section = str(p.section);
  return `${str(p.operation_type) ?? "?"}${section ? `:${section}` : ""}`;
}

/** Eventos admin.operation del backend (con contexto node_id/operation_type).
 * Los del gateway (solo operation_id/state) se ignoran: el backend re-emite
 * cada transición con contexto completo. */
function describeOperation(event: NocEvent, nodeName: (id: string) => string): Described | null {
  const p = event.payload;
  const nodeId = str(p.node_id);
  if (!nodeId) return null; // evento crudo del gateway, sin contexto
  const id = num(p.operation_id);
  const node = nodeName(nodeId);
  const base: Omit<Described, "text" | "severity"> = {
    category: "operacion",
    nodeId,
    batchId: num(p.batch_id) ?? undefined,
    gatewayId: event.gateway_id,
  };
  const attempts = `${num(p.attempts) ?? "?"}/${num(p.max_attempts) ?? "?"}`;
  switch (str(p.state)) {
    case "created":
      return { ...base, severity: "info", text: `Operación #${id} añadida a la cola — ${opLabel(p)} → ${node}` };
    case "dispatched":
      return {
        ...base,
        severity: "info",
        text: `Operación #${id} enviada a la pasarela ${event.gateway_id} (intento ${attempts})`,
      };
    case "running":
      return {
        ...base,
        severity: "info",
        text: `Operación #${id} en ejecución en ${node} — esperando respuesta de la malla`,
      };
    case "retry_scheduled":
      return {
        ...base,
        severity: "warn",
        text: `Operación #${id} sin éxito (${str(p.error) ?? "sin detalle"}); reintento en ${num(p.delay_seconds) ?? "?"}s (intento ${attempts})`,
      };
    case "resend_scheduled":
      return {
        ...base,
        severity: "info",
        text: `Operación #${id} recibió ACK en ${node}, pero se reenvía por redundancia (sin GET de verificación posible) en ${num(p.delay_seconds) ?? "?"}s (intento ${attempts})`,
      };
    case "finished":
      switch (str(p.final_status)) {
        case "succeeded":
          return str(p.verify) === "confirmed"
            ? { ...base, severity: "ok", text: `Operación #${id} completada y verificada en ${node} ✓` }
            : { ...base, severity: "ok", text: `Operación #${id} completada — respuesta recibida de ${node}` };
        case "succeeded_unconfirmed":
          return {
            ...base,
            severity: "warn",
            text: `Operación #${id} aplicada en ${node}, pero la verificación no pudo leerse`,
          };
        case "verify_failed":
          return {
            ...base,
            severity: "error",
            text: `Operación #${id}: verificación fallida — ${node} no refleja el cambio solicitado`,
          };
        case "timeout":
          return { ...base, severity: "error", text: `Operación #${id} agotó el tiempo de espera en ${node} (timeout)` };
        default:
          return {
            ...base,
            severity: "error",
            text: `Operación #${id} fallida en ${node}: ${str(p.error) ?? "sin detalle"}`,
          };
      }
    default:
      return null;
  }
}

function describeBatch(event: NocEvent): Described | null {
  const p = event.payload;
  const batchId = num(p.batch_id);
  const name = str(p.name) ?? "";
  const base: Omit<Described, "text" | "severity"> = { category: "batch", batchId };
  switch (str(p.state)) {
    case "created":
      return {
        ...base,
        severity: "info",
        text: `Batch #${batchId} «${name}» creado — ${num(p.node_count) ?? "?"} nodos (${str(p.operation_type)})`,
      };
    case "paused":
      return { ...base, severity: "warn", text: `Batch #${batchId} «${name}» pausado` };
    case "resumed":
      return { ...base, severity: "info", text: `Batch #${batchId} «${name}» reanudado` };
    case "cancelled":
      return {
        ...base,
        severity: "warn",
        text: `Batch #${batchId} «${name}» cancelado (${num(p.cancelled_pending) ?? 0} pendientes anuladas)`,
      };
    case "completed":
      return { ...base, severity: "ok", text: `Batch #${batchId} «${name}» finalizado correctamente ✓` };
    case "completed_with_errors":
      return { ...base, severity: "error", text: `Batch #${batchId} «${name}» finalizado con errores` };
    default:
      return null;
  }
}

function describeGateway(event: NocEvent): Described | null {
  const p = event.payload;
  const gw = event.gateway_id;
  const transport = str(p.transport) ?? "?";
  const usb = transport === "usb";
  const detail = str(p.detail);
  const base: Omit<Described, "text" | "severity"> = { category: "pasarela", gatewayId: gw };
  switch (str(p.status)) {
    case "connecting":
      return {
        ...base,
        severity: "info",
        text: usb ? `Pasarela ${gw}: conectando por USB…` : `Pasarela ${gw}: conectando (${transport})…`,
      };
    case "connected":
      return {
        ...base,
        severity: "ok",
        text: usb ? `Pasarela ${gw}: conexión USB establecida ✓` : `Pasarela ${gw} conectada (${transport}) ✓`,
      };
    case "disconnected":
      return {
        ...base,
        severity: "error",
        text: usb
          ? `Pasarela ${gw}: USB desconectado — reintentando conexión`
          : `Pasarela ${gw}: conexión perdida — reintentando`,
      };
    case "error":
      return { ...base, severity: "error", text: `Pasarela ${gw}: error de conexión${detail ? ` (${detail})` : ""}` };
    default:
      return null;
  }
}

function describe(event: NocEvent, nodeName: (id: string) => string): Described | null {
  const p = event.payload;
  const nodeId = str(p.node_id);
  switch (event.event_type) {
    case "admin.operation":
      return describeOperation(event, nodeName);
    case "admin.batch":
      return describeBatch(event);
    case "gateway.status":
      return describeGateway(event);
    case "alert.fired": {
      const sev = str(p.severity);
      return {
        category: "alerta",
        severity: sev === "CRITICAL" ? "error" : "warn",
        text: `ALERTA [${sev}] ${str(p.message)}`,
        nodeId: str(p.subject_type) === "node" ? str(p.subject_id) : undefined,
      };
    }
    case "alert.resolved":
      return {
        category: "alerta",
        severity: "ok",
        text: `Alerta resuelta: ${str(p.message)}`,
        nodeId: str(p.subject_type) === "node" ? str(p.subject_id) : undefined,
      };
    case "node.seen":
      return nodeId
        ? { category: "malla", severity: "info", text: `Nodo ${nodeName(nodeId)} visto`, nodeId, gatewayId: event.gateway_id }
        : null;
    case "position.updated":
      return nodeId
        ? { category: "malla", severity: "info", text: `Posición actualizada de ${nodeName(nodeId)}`, nodeId, gatewayId: event.gateway_id }
        : null;
    case "telemetry.received":
      return nodeId
        ? { category: "malla", severity: "info", text: `Telemetría recibida de ${nodeName(nodeId)}`, nodeId, gatewayId: event.gateway_id }
        : null;
    case "message.received": {
      const from = str(p.from_node_id);
      return from
        ? { category: "malla", severity: "info", text: `Mensaje de ${nodeName(from)}`, nodeId: from, gatewayId: event.gateway_id }
        : null;
    }
    default:
      return null;
  }
}

export function toEntry(event: NocEvent, nodeName: (id: string) => string): ActivityEntry | null {
  const d = describe(event, nodeName);
  if (!d) return null;
  return {
    id: event.event_id,
    time: new Date(event.timestamp).toLocaleTimeString(),
    ...d,
  };
}

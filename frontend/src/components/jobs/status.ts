import type { BatchStatus, OperationStatus } from "../../api/client";
import { t } from "../../tokens";

/**
 * Vocabulario y semántica de estados del pipeline admin, COMPARTIDOS por el
 * Centro de Trabajos, el panel Trabajos del Centro de Operaciones y el
 * Inspector. La UI habla el idioma del operador; el estado técnico del
 * contrato queda en el title/tooltip (diario v0.7.0: "succeeded_unconfirmed
 * es jerga de contrato").
 */

export const OP_STATUS_COLOR: Record<OperationStatus, string> = {
  pending: t.textDim,
  queued: t.accent,
  running: t.accent,
  succeeded: t.ok,
  succeeded_unconfirmed: t.warn,
  verify_failed: t.crit,
  failed: t.crit,
  timeout: t.warn,
  cancelled: t.textFaint,
};

export const OP_STATUS_LABEL: Record<OperationStatus, string> = {
  pending: "pendiente",
  queued: "en cola",
  running: "en curso",
  succeeded: "confirmada",
  succeeded_unconfirmed: "aplicada · sin verificar",
  verify_failed: "verificación fallida",
  failed: "fallida",
  timeout: "sin respuesta",
  cancelled: "cancelada",
};

export const BATCH_STATUS_COLOR: Record<BatchStatus, string> = {
  running: t.accent,
  paused: t.warn,
  cancelled: t.textFaint,
  completed: t.ok,
  completed_with_errors: t.crit,
};

export const BATCH_STATUS_LABEL: Record<BatchStatus, string> = {
  running: "en ejecución",
  paused: "pausado",
  cancelled: "cancelado",
  completed: "completado",
  completed_with_errors: "con errores",
};

/** Estados terminales de operación (no cambian solos). */
export const TERMINAL_OP_STATUSES = new Set<OperationStatus>([
  "succeeded",
  "succeeded_unconfirmed",
  "verify_failed",
  "failed",
  "timeout",
  "cancelled",
]);

/** Terminales que piden intervención del operador. */
export const FAILED_OP_STATUSES = new Set<OperationStatus>(["verify_failed", "failed", "timeout"]);

/** Reintentables mediante retry manual (re-evalúa el enrutado, M6.2). */
export const RETRYABLE_OP_STATUSES = new Set<OperationStatus>([
  "failed",
  "timeout",
  "verify_failed",
  "cancelled",
]);

// ADR 0019: estas operaciones jamás pueden llegar a "succeeded" (no existe
// lectura de verificación posible en el firmware); su techo es "aplicada".
export const ACK_ONLY_NO_VERIFY = new Set([
  "favorite.set",
  "favorite.remove",
  "ignored.set",
  "ignored.remove",
  "contact.add",
]);

export const ACK_ONLY_NOTE =
  "El firmware no expone ninguna forma de leer de vuelta favoritos/ignorados/ficha de contacto: " +
  "esta operación solo puede confirmarse por ACK del dispositivo, nunca por lectura posterior. " +
  "«aplicada · sin verificar» es su techo máximo posible, no un problema.";

export function fmtSeconds(s: number | null | undefined): string {
  if (s == null) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}m ${Math.round(s % 60)}s`;
  return `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m`;
}

/** Etiqueta compacta del tipo: sección para SETs/GETs, perfil para profile.sync */
export function batchTypeLabel(operationType: string, params: Record<string, unknown>): string {
  if (typeof params.profile_name === "string") {
    return `${operationType}:${params.profile_name} v${String(params.version ?? "?")}`;
  }
  return `${operationType}${typeof params.section === "string" ? `:${params.section}` : ""}`;
}

export function opTypeLabel(operationType: string, params: Record<string, unknown>): string {
  return `${operationType}${typeof params.section === "string" ? `:${params.section}` : ""}`;
}

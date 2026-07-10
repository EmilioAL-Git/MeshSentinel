import type { NocEvent } from "./api/client";

/**
 * Cierre del ciclo mental del operador (diario v0.7.2): las operaciones
 * lanzadas EN ESTA SESIÓN se registran aquí y, cuando su evento
 * admin.operation llega a estado terminal por WS, se emite un toast con el
 * resultado. Solo memoria de sesión — nada se persiste; el registro
 * completo sigue siendo la vista Operaciones.
 */

const tracked = new Set<number>();

export function trackOperations(ids: number[]): void {
  for (const id of ids) tracked.add(id);
}

const FINAL_LABEL: Record<string, { text: string; kind: "ok" | "error" }> = {
  succeeded: { text: "completada y verificada ✓", kind: "ok" },
  succeeded_unconfirmed: { text: "aplicada (sin verificación posible)", kind: "ok" },
  verify_failed: { text: "verificación fallida", kind: "error" },
  failed: { text: "fallida", kind: "error" },
  timeout: { text: "sin respuesta (timeout)", kind: "error" },
  cancelled: { text: "cancelada", kind: "error" },
};

/**
 * Procesa un evento WS; si corresponde al final de una operación registrada,
 * devuelve el mensaje de toast (y deja de seguirla). Null en caso contrario.
 */
export function consumeFinished(event: NocEvent): { text: string; kind: "ok" | "error" } | null {
  if (event.event_type !== "admin.operation") return null;
  const p = event.payload;
  if (p.state !== "finished" || typeof p.operation_id !== "number") return null;
  if (!tracked.has(p.operation_id)) return null;
  tracked.delete(p.operation_id);
  const label = FINAL_LABEL[String(p.final_status)] ?? { text: `terminada (${String(p.final_status)})`, kind: "ok" as const };
  const type = typeof p.operation_type === "string" ? p.operation_type : "operación";
  return { text: `${type} #${p.operation_id}: ${label.text}`, kind: label.kind };
}

import type { OperationOut } from "../../api/client";
import { t } from "../../tokens";
import { FAILED_OP_STATUSES, TERMINAL_OP_STATUSES } from "./status";

/** Un punto por intento permitido: gris sin usar, ámbar gastado, azul en curso, verde éxito. */
export function AttemptDots({ op }: { op: Pick<OperationOut, "attempts" | "max_attempts" | "status"> }) {
  const retries = op.attempts - 1;
  return (
    <span
      style={{ display: "inline-flex", alignItems: "center", gap: 3, whiteSpace: "nowrap" }}
      title={`Intento ${op.attempts} de ${op.max_attempts}`}
    >
      {Array.from({ length: op.max_attempts }, (_, i) => {
        const last = i === op.attempts - 1;
        const dot =
          i >= op.attempts
            ? "var(--border)"
            : last && TERMINAL_OP_STATUSES.has(op.status) && !FAILED_OP_STATUSES.has(op.status)
              ? t.ok
              : last && !TERMINAL_OP_STATUSES.has(op.status)
                ? t.accent
                : t.warn;
        return <span key={i} style={{ width: 8, height: 8, borderRadius: "50%", background: dot, display: "inline-block" }} />;
      })}
      {retries > 0 && (
        <span style={{ fontSize: 11, color: "var(--warn)", marginLeft: 4 }}>
          ↻ {retries} reintento{retries > 1 ? "s" : ""}
        </span>
      )}
    </span>
  );
}

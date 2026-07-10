import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, type CSSProperties, type ReactNode } from "react";
import {
  cancelBatch,
  cancelOperation,
  fetchBatches,
  pauseBatch,
  resumeBatch,
  retryOperation,
  type BatchDetailOut,
  type NodeSummaryOut,
  type OperationOut,
} from "../../api/client";
import { relativeTime } from "../../time";
import { chipStyle, t } from "../../tokens";

/**
 * Panel Trabajos del Centro de Operaciones (v0.7 §6.4): el pipeline admin en
 * un solo sitio — en curso / cola / recientes — con las acciones inline
 * (pausar, cancelar, reintentar). Reutiliza íntegras las mutaciones y
 * queries de M1.1/M2; la vista fusionada con historial completo llega en
 * una fase posterior.
 */

const sectionTitle: CSSProperties = {
  color: t.textFaint,
  fontSize: 10.5,
  letterSpacing: "0.08em",
  fontWeight: 600,
  padding: "0.55rem 0.75rem 0.2rem",
};

const rowStyle: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  gap: "0.4rem",
  padding: "0.18rem 0.75rem",
  fontSize: 12,
};

const smallBtn: CSSProperties = {
  background: "transparent",
  border: `1px solid ${t.border}`,
  color: t.text,
  borderRadius: 4,
  cursor: "pointer",
  fontSize: 11,
  padding: "0 0.45rem",
};

const RETRYABLE = new Set(["failed", "timeout", "verify_failed", "cancelled"]);
const TERMINAL = new Set(["succeeded", "succeeded_unconfirmed", "verify_failed", "failed", "timeout", "cancelled"]);

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <div style={sectionTitle}>{title}</div>
      {children}
    </div>
  );
}

function opLabel(op: OperationOut): string {
  const section = typeof op.params.section === "string" ? `:${op.params.section}` : "";
  return `${op.operation_type}${section}`;
}

export function JobsPanel({
  operations,
  summaries,
  runningBatch,
  onGoTo,
}: {
  operations: OperationOut[];
  summaries: NodeSummaryOut[];
  runningBatch: BatchDetailOut | undefined;
  onGoTo: (view: string) => void;
}) {
  const queryClient = useQueryClient();
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["operations"] });
    queryClient.invalidateQueries({ queryKey: ["batches"] });
    queryClient.invalidateQueries({ queryKey: ["batch"] });
  };
  const doPause = useMutation({ mutationFn: pauseBatch, onSettled: invalidate });
  const doResume = useMutation({ mutationFn: resumeBatch, onSettled: invalidate });
  const doCancelBatch = useMutation({ mutationFn: cancelBatch, onSettled: invalidate });
  const doCancelOp = useMutation({ mutationFn: cancelOperation, onSettled: invalidate });
  const doRetryOp = useMutation({ mutationFn: retryOperation, onSettled: invalidate });

  const batches = useQuery({
    queryKey: ["batches", "jobs-panel"],
    queryFn: () => fetchBatches({ limit: 10 }),
    refetchInterval: 30_000,
  });
  const activeBatches = (batches.data ?? []).filter((b) => b.status === "running" || b.status === "paused");

  const nodeName = useMemo(() => {
    const map = new Map(summaries.map((s) => [s.node.node_id, s.node.short_name ?? s.node.node_id]));
    return (id: string) => map.get(id) ?? id;
  }, [summaries]);

  const running = operations.filter((o) => o.status === "running");
  const queued = operations.filter((o) => o.status === "pending" || o.status === "queued");
  const recent = operations
    .filter((o) => TERMINAL.has(o.status))
    .sort((a, b) => ((a.finished_at ?? "") < (b.finished_at ?? "") ? 1 : -1))
    .slice(0, 5);
  const inFlight = running.length + activeBatches.length;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.4rem",
          padding: "0.5rem 0.75rem",
          borderBottom: `1px solid ${t.borderSubtle}`,
        }}
      >
        <span style={{ color: t.textDim, fontSize: 11, letterSpacing: "0.08em", fontWeight: 600 }}>TRABAJOS</span>
        {inFlight > 0 && <span style={{ ...chipStyle(t.accent), fontSize: 10.5 }}>▶ {inFlight}</span>}
        <button
          style={{ ...smallBtn, marginLeft: "auto" }}
          onClick={() => onGoTo("operations")}
          title="Cola e historial completos (vista Operaciones)"
        >
          Ver historial →
        </button>
      </div>
      <div style={{ flex: 1, overflowY: "auto", paddingBottom: "0.5rem" }}>
        <Section title="EN CURSO">
          {activeBatches.length === 0 && running.length === 0 && (
            <div style={{ ...rowStyle, color: t.textFaint }}>Nada en ejecución.</div>
          )}
          {activeBatches.map((b) => {
            const detail = runningBatch?.id === b.id ? runningBatch : undefined;
            const pct = detail ? Math.round(detail.progress.percent) : null;
            return (
              <div key={b.id} style={{ padding: "0.25rem 0.75rem" }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: "0.4rem", fontSize: 12 }}>
                  <span style={{ color: b.status === "paused" ? t.warn : t.accent }}>
                    {b.status === "paused" ? "⏸" : "▶"}
                  </span>
                  <span style={{ color: t.text, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    lote #{b.id} {b.name}
                  </span>
                  {b.status === "running" ? (
                    <button style={smallBtn} title="Pausar" onClick={() => doPause.mutate(b.id)}>⏸</button>
                  ) : (
                    <button style={smallBtn} title="Reanudar" onClick={() => doResume.mutate(b.id)}>▶</button>
                  )}
                  <button style={smallBtn} title="Cancelar pendientes" onClick={() => doCancelBatch.mutate(b.id)}>✕</button>
                </div>
                {detail && (
                  <div style={{ paddingLeft: "1.1rem" }}>
                    <div style={{ background: t.surface2, borderRadius: 3, height: 5, marginTop: 3, overflow: "hidden" }}>
                      <div
                        style={{
                          width: `${detail.progress.percent}%`,
                          height: "100%",
                          background: b.status === "paused" ? t.warn : t.accent,
                          transition: "width 400ms ease-out",
                        }}
                      />
                    </div>
                    <div style={{ color: t.textFaint, fontSize: 11, fontFamily: t.fontMono, marginTop: 2 }}>
                      {detail.progress.done}/{detail.progress.total} · {pct} %
                      {detail.progress.eta_seconds > 0 && ` · ETA ${Math.ceil(detail.progress.eta_seconds / 60)}m`}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          {running.map((op) => (
            <div key={op.id} style={rowStyle}>
              <span style={{ color: t.accent }}>⚙</span>
              <span style={{ color: t.text }}>#{op.id} {opLabel(op)}</span>
              <span style={{ color: t.textDim, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {nodeName(op.target_node_id)}
              </span>
              <span style={{ color: t.textFaint, fontFamily: t.fontMono, fontSize: 11 }}>{op.gateway_id}</span>
            </div>
          ))}
        </Section>

        <Section title={`COLA (${queued.length})`}>
          {queued.length === 0 && <div style={{ ...rowStyle, color: t.textFaint }}>Cola vacía.</div>}
          {queued.slice(0, 6).map((op) => (
            <div key={op.id} style={rowStyle}>
              <span style={{ color: t.textDim }}>⧗</span>
              <span style={{ color: t.text }}>{opLabel(op)}</span>
              <span style={{ color: t.textDim, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {nodeName(op.target_node_id)}
              </span>
              {op.status === "pending" && (
                <button style={smallBtn} title="Cancelar" onClick={() => doCancelOp.mutate(op.id)}>✕</button>
              )}
            </div>
          ))}
          {queued.length > 6 && (
            <div style={{ ...rowStyle, color: t.textFaint }}>… y {queued.length - 6} más</div>
          )}
        </Section>

        <Section title="RECIENTES">
          {recent.length === 0 && <div style={{ ...rowStyle, color: t.textFaint }}>Sin operaciones recientes.</div>}
          {recent.map((op) => {
            const ok = op.status === "succeeded" || op.status === "succeeded_unconfirmed";
            return (
              <div key={op.id} style={rowStyle}>
                <span style={{ color: ok ? t.ok : t.crit }}>{ok ? "✓" : "✗"}</span>
                <span style={{ color: t.text }}>{opLabel(op)}</span>
                <span style={{ color: t.textDim, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {nodeName(op.target_node_id)}
                </span>
                <span style={{ color: t.textFaint, fontFamily: t.fontMono, fontSize: 11 }}>
                  {relativeTime(op.finished_at)}
                </span>
                {RETRYABLE.has(op.status) && (
                  <button style={smallBtn} title="Reintentar (re-evalúa la pasarela)" onClick={() => doRetryOp.mutate(op.id)}>
                    ↻
                  </button>
                )}
              </div>
            );
          })}
        </Section>
      </div>
    </div>
  );
}

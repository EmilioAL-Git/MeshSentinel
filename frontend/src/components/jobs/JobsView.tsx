import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import {
  cancelBatch,
  cancelOperation,
  fetchBatch,
  fetchBatchOperations,
  fetchBatches,
  fetchOperations,
  pauseBatch,
  resumeBatch,
  retryOperation,
  type BatchOut,
  type NodeSummaryOut,
  type OperationOut,
} from "../../api/client";
import { relativeTime } from "../../time";
import { chipStyle, t } from "../../tokens";
import { NodeSelect } from "../NodeSelect";
import { toast } from "../shell/Toast";
import { NewOperationForm } from "./NewOperationForm";
import {
  ACK_ONLY_NO_VERIFY,
  ACK_ONLY_NOTE,
  BATCH_STATUS_COLOR,
  BATCH_STATUS_LABEL,
  FAILED_OP_STATUSES,
  fmtSeconds,
  OP_STATUS_COLOR,
  OP_STATUS_LABEL,
  opTypeLabel,
  RETRYABLE_OP_STATUSES,
  TERMINAL_OP_STATUSES,
  batchTypeLabel,
} from "./status";

/**
 * Centro de Trabajos (v0.7.4): TODO el pipeline admin en una consola —
 * sustituye a las vistas Operaciones y Batches. Organizada por la pregunta
 * del operador, no por el modelo de datos: ¿qué se está haciendo? ¿qué
 * espera? ¿qué necesita mi intervención? ¿qué pasó? Un lote y sus
 * operaciones viven juntos; el detalle de nodo es el Inspector global.
 */

const sectionTitle: CSSProperties = {
  color: t.textDim,
  fontSize: 11,
  letterSpacing: "0.08em",
  fontWeight: 600,
  margin: "0 0 6px",
};

const smallBtn: CSSProperties = {
  background: "transparent",
  border: `1px solid ${t.border}`,
  color: t.text,
  borderRadius: 4,
  cursor: "pointer",
  fontSize: 11,
  padding: "0.1rem 0.5rem",
  whiteSpace: "nowrap",
};

const cardStyle: CSSProperties = {
  background: t.surface,
  border: `1px solid ${t.border}`,
  borderRadius: 6,
  padding: "0.6rem 0.8rem",
  marginBottom: 8,
};

const rowStyle: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  gap: "0.5rem",
  padding: "0.22rem 0.4rem",
  fontSize: 12.5,
  borderRadius: 4,
};

const inputStyle: CSSProperties = {
  background: t.bg,
  border: `1px solid ${t.border}`,
  color: t.text,
  borderRadius: 6,
  padding: "0.25rem 0.5rem",
  fontSize: 12,
};

function OpChip({ op }: { op: OperationOut }) {
  return (
    <span
      style={{ ...chipStyle(OP_STATUS_COLOR[op.status]), fontSize: 10.5 }}
      title={
        (op.status === "succeeded_unconfirmed" && ACK_ONLY_NO_VERIFY.has(op.operation_type)
          ? ACK_ONLY_NOTE + " · "
          : "") + `estado técnico: ${op.status}`
      }
    >
      {OP_STATUS_LABEL[op.status]}
    </span>
  );
}

function Section({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  return (
    <section style={{ marginBottom: 18 }}>
      <div style={sectionTitle}>
        {title}
        {count != null && count > 0 && (
          <span style={{ fontFamily: t.fontMono, marginLeft: 6 }}>({count})</span>
        )}
      </div>
      {children}
    </section>
  );
}

/** Fila de operación: las mismas acciones en cualquier sección. */
function OpRow({
  op,
  nodeName,
  flash,
  focusId,
  onOpenNode,
  onLocate,
  onCancel,
  onRetry,
  showTime,
}: {
  op: OperationOut;
  nodeName: (id: string) => string;
  flash: boolean;
  focusId: string | null;
  onOpenNode: (id: string) => void;
  onLocate: (id: string) => void;
  onCancel?: (id: number) => void;
  onRetry?: (id: number) => void;
  showTime?: "created" | "finished";
}) {
  return (
    <div
      className={flash ? "noc-flash" : undefined}
      style={{
        ...rowStyle,
        background: focusId != null && op.target_node_id === focusId ? t.accentTint : undefined,
      }}
    >
      <span style={{ color: t.textFaint, fontFamily: t.fontMono, fontSize: 11 }}>#{op.id}</span>
      <span style={{ fontFamily: t.fontMono, color: t.text }}>{opTypeLabel(op.operation_type, op.params)}</span>
      <span
        onClick={() => onOpenNode(op.target_node_id)}
        title="Abrir en el Inspector"
        style={{ color: t.textDim, cursor: "pointer", flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
      >
        {nodeName(op.target_node_id)}
      </span>
      <span style={{ color: t.textFaint, fontFamily: t.fontMono, fontSize: 11 }}>{op.gateway_id}</span>
      <OpChip op={op} />
      {showTime && (
        <span style={{ color: t.textFaint, fontFamily: t.fontMono, fontSize: 11 }}>
          {relativeTime(showTime === "created" ? op.created_at : op.finished_at)}
        </span>
      )}
      <button style={smallBtn} title="Localizar en el mapa" onClick={() => onLocate(op.target_node_id)}>
        ⌖
      </button>
      {onRetry && RETRYABLE_OP_STATUSES.has(op.status) && (
        <button style={smallBtn} title="Reintentar (re-evalúa la pasarela)" onClick={() => onRetry(op.id)}>
          ↻
        </button>
      )}
      {onCancel && op.status === "pending" && (
        <button style={smallBtn} title="Cancelar" onClick={() => onCancel(op.id)}>
          ✕
        </button>
      )}
    </div>
  );
}

/** Tarjeta de lote activo: progreso, reparto por pasarela, ETA, velocidad. */
function ActiveBatchCard({
  batch,
  batchOps,
  nodeName,
  flash,
  focusId,
  expanded,
  onToggleExpand,
  onOpenNode,
  onLocate,
  onRetry,
}: {
  batch: BatchOut;
  batchOps: OperationOut[];
  nodeName: (id: string) => string;
  flash: boolean;
  focusId: string | null;
  expanded: boolean;
  onToggleExpand: () => void;
  onOpenNode: (id: string) => void;
  onLocate: (id: string) => void;
  onRetry: (id: number) => void;
}) {
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ["batch", batch.id],
    queryFn: () => fetchBatch(batch.id),
    refetchInterval: 5_000,
  });
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["batch", batch.id] });
    queryClient.invalidateQueries({ queryKey: ["batches"] });
    queryClient.invalidateQueries({ queryKey: ["operations"] });
  };
  const doPause = useMutation({ mutationFn: () => pauseBatch(batch.id), onSettled: invalidate });
  const doResume = useMutation({ mutationFn: () => resumeBatch(batch.id), onSettled: invalidate });
  const doCancel = useMutation({
    mutationFn: () => cancelBatch(batch.id),
    onSuccess: () => toast(`Lote #${batch.id}: pendientes canceladas`),
    onSettled: invalidate,
  });
  const [cancelArmed, setCancelArmed] = useState(false);

  const p = detail.data?.progress;
  const paused = batch.status === "paused";

  // Reparto Multi-Gateway (M6.2): hecho/total por pasarela, de las propias ops
  const perGateway = useMemo(() => {
    const acc = new Map<string, { total: number; done: number }>();
    for (const op of batchOps) {
      const entry = acc.get(op.gateway_id) ?? { total: 0, done: 0 };
      entry.total += 1;
      if (TERMINAL_OP_STATUSES.has(op.status)) entry.done += 1;
      acc.set(op.gateway_id, entry);
    }
    return [...acc.entries()].sort((a, b) => b[1].total - a[1].total);
  }, [batchOps]);

  const failed = batchOps.filter((o) => FAILED_OP_STATUSES.has(o.status));

  return (
    <div className={flash ? "noc-flash" : undefined} style={{ ...cardStyle, borderLeft: `3px solid ${paused ? t.warn : t.accent}` }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "0.5rem", flexWrap: "wrap" }}>
        <span style={{ color: paused ? t.warn : t.accent }}>{paused ? "⏸" : "▶"}</span>
        <strong style={{ fontSize: 13 }}>#{batch.id} {batch.name}</strong>
        <span style={{ fontFamily: t.fontMono, color: t.textDim, fontSize: 11.5 }}>
          {batchTypeLabel(batch.operation_type, batch.params)}
        </span>
        <span style={{ ...chipStyle(BATCH_STATUS_COLOR[batch.status]), fontSize: 10.5 }}>
          {BATCH_STATUS_LABEL[batch.status]}
        </span>
        <span style={{ marginLeft: "auto", display: "inline-flex", gap: 4 }}>
          {batch.status === "running" && (
            <button style={smallBtn} onClick={() => doPause.mutate()}>⏸ Pausar</button>
          )}
          {paused && <button style={smallBtn} onClick={() => doResume.mutate()}>▶ Reanudar</button>}
          {cancelArmed ? (
            <button
              style={{ ...smallBtn, background: t.crit, borderColor: t.crit, color: "#fff" }}
              onClick={() => { doCancel.mutate(); setCancelArmed(false); }}
            >
              ¿Cancelar {p?.counts["pending"] ?? "las"} pendientes?
            </button>
          ) : (
            <button style={smallBtn} onClick={() => setCancelArmed(true)}>✕</button>
          )}
        </span>
      </div>

      {p && (
        <>
          <div style={{ background: t.surface2, borderRadius: 4, height: 8, marginTop: 8, overflow: "hidden" }}>
            <div
              style={{
                width: `${p.percent}%`,
                height: "100%",
                background: paused ? t.warn : t.accent,
                transition: "width 400ms ease-out",
              }}
            />
          </div>
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", color: t.textDim, fontFamily: t.fontMono, fontSize: 11.5, marginTop: 4 }}>
            <span>{p.done}/{p.total} · {Math.round(p.percent)} %</span>
            {p.rate_per_minute != null && <span>{p.rate_per_minute.toFixed(1)} op/min</span>}
            {p.eta_seconds > 0 && !paused && <span>ETA {fmtSeconds(p.eta_seconds)}</span>}
            {p.current_node_id && (
              <span style={{ cursor: "pointer" }} onClick={() => onOpenNode(p.current_node_id!)} title="Abrir en el Inspector">
                ahora: {nodeName(p.current_node_id)}
              </span>
            )}
            {failed.length > 0 && <span style={{ color: t.crit }}>{failed.length} fallidas</span>}
          </div>
        </>
      )}

      {/* Reparto por pasarela (M6.2): visible sin abrir nada */}
      {perGateway.length > 0 && (
        <div style={{ display: "flex", gap: "0.9rem", flexWrap: "wrap", marginTop: 6 }}>
          {perGateway.map(([gw, c]) => (
            <span key={gw} style={{ display: "inline-flex", alignItems: "center", gap: 5, fontFamily: t.fontMono, fontSize: 11, color: t.textDim }}>
              🛰 {gw}
              <span style={{ display: "inline-block", width: 54, height: 5, background: t.surface2, borderRadius: 3, overflow: "hidden" }}>
                <span style={{ display: "block", width: `${c.total ? (c.done / c.total) * 100 : 0}%`, height: "100%", background: t.accent, transition: "width 400ms ease-out" }} />
              </span>
              {c.done}/{c.total}
            </span>
          ))}
        </div>
      )}

      <button
        style={{ ...smallBtn, marginTop: 7, border: "none", color: t.accent, padding: 0 }}
        onClick={onToggleExpand}
      >
        {expanded ? "▾ Ocultar operaciones" : `▸ Ver operaciones (${batchOps.length})`}
      </button>
      {expanded && (
        <div style={{ marginTop: 4, borderTop: `1px solid ${t.borderSubtle}`, paddingTop: 4 }}>
          {batchOps.map((op) => (
            <OpRow
              key={op.id}
              op={op}
              nodeName={nodeName}
              flash={false}
              focusId={focusId}
              onOpenNode={onOpenNode}
              onLocate={onLocate}
              onRetry={onRetry}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** Grupo de lote terminado en el historial: resumen + expandible. */
function HistoryBatchCard({
  batch,
  nodeName,
  flash,
  focusId,
  expanded,
  onToggleExpand,
  onOpenNode,
  onLocate,
  onRetry,
}: {
  batch: BatchOut;
  nodeName: (id: string) => string;
  flash: boolean;
  focusId: string | null;
  expanded: boolean;
  onToggleExpand: () => void;
  onOpenNode: (id: string) => void;
  onLocate: (id: string) => void;
  onRetry: (id: number) => void;
}) {
  const ops = useQuery({
    queryKey: ["batch-ops", batch.id],
    queryFn: () => fetchBatchOperations(batch.id),
    enabled: expanded,
  });
  return (
    <div className={flash ? "noc-flash" : undefined} style={{ ...cardStyle, padding: "0.45rem 0.7rem" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "0.5rem", flexWrap: "wrap", cursor: "pointer" }} onClick={onToggleExpand}>
        <span style={{ color: t.textFaint, fontSize: 10 }}>{expanded ? "▾" : "▸"}</span>
        <span style={{ fontFamily: t.fontMono, color: t.textFaint, fontSize: 11 }}>#{batch.id}</span>
        <span style={{ color: t.text, fontSize: 12.5 }}>{batch.name}</span>
        <span style={{ fontFamily: t.fontMono, color: t.textDim, fontSize: 11 }}>
          {batchTypeLabel(batch.operation_type, batch.params)} · {batch.node_count} nodos
        </span>
        <span style={{ ...chipStyle(BATCH_STATUS_COLOR[batch.status]), fontSize: 10.5 }}>
          {BATCH_STATUS_LABEL[batch.status]}
        </span>
        <span style={{ marginLeft: "auto", color: t.textFaint, fontFamily: t.fontMono, fontSize: 11 }}>
          {relativeTime(batch.finished_at ?? batch.created_at)}
        </span>
      </div>
      {expanded && (
        <div style={{ marginTop: 4, borderTop: `1px solid ${t.borderSubtle}`, paddingTop: 4 }}>
          {ops.isLoading && <div style={{ color: t.textFaint, fontSize: 12 }}>Cargando…</div>}
          {(ops.data ?? []).map((op) => (
            <OpRow
              key={op.id}
              op={op}
              nodeName={nodeName}
              flash={false}
              focusId={focusId}
              onOpenNode={onOpenNode}
              onLocate={onLocate}
              onRetry={onRetry}
              showTime="finished"
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function JobsView({
  summaries,
  focusId,
  openBatchId,
  onOpenNode,
  onLocate,
}: {
  summaries: NodeSummaryOut[];
  focusId: string | null;
  /** Lote a expandir al entrar (llegando desde Perfiles o el wizard). */
  openBatchId: number | null;
  onOpenNode: (nodeId: string) => void;
  onLocate: (nodeId: string) => void;
}) {
  const queryClient = useQueryClient();
  const operations = useQuery({
    queryKey: ["operations", "jobs"],
    queryFn: () => fetchOperations(undefined, 500),
    refetchInterval: 10_000,
  });
  const batches = useQuery({
    queryKey: ["batches", "list"],
    queryFn: () => fetchBatches({ limit: 50 }),
    refetchInterval: 15_000,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["operations"] });
    queryClient.invalidateQueries({ queryKey: ["batches"] });
  };
  const doCancelOp = useMutation({ mutationFn: cancelOperation, onSettled: invalidate });
  const doRetryOp = useMutation({
    mutationFn: retryOperation,
    onSuccess: () => toast("Reintento encolado (re-evalúa la pasarela)"),
    onSettled: invalidate,
  });

  // Filtros: nodo / tipo / pasarela — se aplican a cola, intervención e historial
  const [nodeFilter, setNodeFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [gwFilter, setGwFilter] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [expandedBatch, setExpandedBatch] = useState<number | null>(openBatchId);
  useEffect(() => {
    if (openBatchId != null) setExpandedBatch(openBatchId);
  }, [openBatchId]);

  const allOps = useMemo(() => operations.data ?? [], [operations.data]);
  const allBatches = useMemo(() => batches.data ?? [], [batches.data]);

  const opTypes = useMemo(() => [...new Set(allOps.map((o) => o.operation_type))].sort(), [allOps]);
  const gwIds = useMemo(() => [...new Set(allOps.map((o) => o.gateway_id))].sort(), [allOps]);

  const matches = (op: OperationOut) =>
    (nodeFilter === "" || op.target_node_id === nodeFilter) &&
    (typeFilter === "" || op.operation_type === typeFilter) &&
    (gwFilter === "" || op.gateway_id === gwFilter);
  const filtering = nodeFilter !== "" || typeFilter !== "" || gwFilter !== "";

  const nodeName = useMemo(() => {
    const map = new Map(summaries.map((s) => [s.node.node_id, s.node.short_name ?? s.node.node_id]));
    return (id: string) => map.get(id) ?? id;
  }, [summaries]);

  // Transiciones visibles sin refresco brusco: destello one-shot al cambiar
  // el estado de una op o lote respecto al último render con datos.
  const prevStatuses = useRef<Map<string, string>>(new Map());
  const [flashed, setFlashed] = useState<Set<string>>(new Set());
  useEffect(() => {
    const changed = new Set<string>();
    const next = new Map<string, string>();
    for (const op of allOps) {
      const key = `op:${op.id}`;
      next.set(key, op.status);
      const prev = prevStatuses.current.get(key);
      if (prev != null && prev !== op.status) changed.add(key);
    }
    for (const b of allBatches) {
      const key = `batch:${b.id}`;
      next.set(key, b.status);
      const prev = prevStatuses.current.get(key);
      if (prev != null && prev !== b.status) changed.add(key);
    }
    prevStatuses.current = next;
    if (changed.size === 0) return;
    setFlashed(changed);
    const timer = window.setTimeout(() => setFlashed(new Set()), 1_300);
    return () => window.clearTimeout(timer);
  }, [allOps, allBatches]);
  const flash = (key: string) => flashed.has(key);

  // ── Clasificación por pregunta del operador ────────────────────────────────
  const activeBatches = allBatches.filter((b) => b.status === "running" || b.status === "paused");
  const activeBatchIds = new Set(activeBatches.map((b) => b.id));
  const opsByBatch = useMemo(() => {
    const acc = new Map<number, OperationOut[]>();
    for (const op of allOps) {
      if (op.batch_id == null) continue;
      const list = acc.get(op.batch_id) ?? [];
      list.push(op);
      acc.set(op.batch_id, list);
    }
    return acc;
  }, [allOps]);

  const runningOps = allOps.filter((o) => o.status === "running" && !activeBatchIds.has(o.batch_id ?? -1));
  const queuedOps = allOps.filter(
    (o) => (o.status === "pending" || o.status === "queued") && !activeBatchIds.has(o.batch_id ?? -1) && matches(o),
  );
  // Intervención: fallidas de las últimas 24 h que siguen sin reintento posterior
  const dayAgo = Date.now() - 24 * 3600 * 1000;
  const needsAttention = allOps.filter(
    (o) =>
      FAILED_OP_STATUSES.has(o.status) &&
      matches(o) &&
      (o.finished_at == null || new Date(o.finished_at).getTime() > dayAgo),
  );
  // Historial: terminales (ops sueltas) + lotes terminados, misma línea temporal
  const doneBatches = allBatches.filter((b) => !activeBatchIds.has(b.id));
  const doneStandaloneOps = allOps.filter(
    (o) => o.batch_id == null && TERMINAL_OP_STATUSES.has(o.status) && !FAILED_OP_STATUSES.has(o.status) && matches(o),
  );
  const history: { ts: string; item: ReactNode }[] = [
    ...doneBatches
      .filter((b) => nodeFilter === "" || (opsByBatch.get(b.id) ?? []).some((o) => matches(o)))
      .map((b) => ({
        ts: b.finished_at ?? b.created_at ?? "",
        item: (
          <HistoryBatchCard
            key={`b${b.id}`}
            batch={b}
            nodeName={nodeName}
            flash={flash(`batch:${b.id}`)}
            focusId={focusId}
            expanded={expandedBatch === b.id}
            onToggleExpand={() => setExpandedBatch(expandedBatch === b.id ? null : b.id)}
            onOpenNode={onOpenNode}
            onLocate={onLocate}
            onRetry={(id) => doRetryOp.mutate(id)}
          />
        ),
      })),
    ...doneStandaloneOps.map((o) => ({
      ts: o.finished_at ?? o.created_at ?? "",
      item: (
        <OpRow
          key={`o${o.id}`}
          op={o}
          nodeName={nodeName}
          flash={flash(`op:${o.id}`)}
          focusId={focusId}
          onOpenNode={onOpenNode}
          onLocate={onLocate}
          onRetry={(id) => doRetryOp.mutate(id)}
          showTime="finished"
        />
      ),
    })),
  ]
    .sort((a, b) => (a.ts < b.ts ? 1 : -1))
    .slice(0, 40);

  // Estadísticas rápidas interpretadas (últimas 24 h sobre lo cargado)
  const recent = allOps.filter((o) => o.finished_at != null && new Date(o.finished_at).getTime() > dayAgo);
  const okCount = recent.filter((o) => o.status === "succeeded" || o.status === "succeeded_unconfirmed").length;
  const koCount = recent.filter((o) => FAILED_OP_STATUSES.has(o.status)).length;
  const durations = recent.map((o) => o.duration_ms).filter((d): d is number => d != null).sort((a, b) => a - b);
  const medianMs = durations.length > 0 ? durations[Math.floor(durations.length / 2)] : null;

  return (
    <div>
      {/* Cabecera de la consola: estadísticas interpretadas + acciones */}
      <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap", marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: "1.05rem" }}>Trabajos</h2>
        <span style={{ fontFamily: t.fontMono, fontSize: 11.5, color: t.textDim }}>
          24 h: <span style={{ color: t.ok }}>{okCount} ✓</span>
          {" · "}
          <span style={{ color: koCount > 0 ? t.crit : t.textDim }}>{koCount} ✗</span>
          {medianMs != null && <> · mediana {fmtSeconds(medianMs / 1000)}</>}
        </span>
        <span style={{ marginLeft: "auto", display: "inline-flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          <NodeSelect value={nodeFilter} onChange={setNodeFilter} options={summaries} placeholder="— todos los nodos —" />
          <select style={inputStyle} value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
            <option value="">— tipo —</option>
            {opTypes.map((x) => (
              <option key={x} value={x}>{x}</option>
            ))}
          </select>
          <select style={inputStyle} value={gwFilter} onChange={(e) => setGwFilter(e.target.value)}>
            <option value="">— pasarela —</option>
            {gwIds.map((x) => (
              <option key={x} value={x}>{x}</option>
            ))}
          </select>
          {filtering && (
            <button style={smallBtn} onClick={() => { setNodeFilter(""); setTypeFilter(""); setGwFilter(""); }}>
              Limpiar
            </button>
          )}
          <button
            style={{ ...smallBtn, background: t.accentTint, borderColor: t.accent, color: t.accent }}
            onClick={() => setShowForm(!showForm)}
          >
            ＋ Nueva operación
          </button>
        </span>
      </div>

      {showForm && <NewOperationForm summaries={summaries} onClose={() => setShowForm(false)} />}

      <div className="jobs-grid">
        {/* Columna viva: qué hace la red, qué espera, qué pide intervención */}
        <div>
          <Section title="EN EJECUCIÓN" count={activeBatches.length + runningOps.length}>
            {activeBatches.length === 0 && runningOps.length === 0 && (
              <p style={{ color: t.textFaint, fontSize: 12.5, margin: "0.2rem 0" }}>
                La red no está ejecutando ningún trabajo ahora mismo.
              </p>
            )}
            {activeBatches.map((b) => (
              <ActiveBatchCard
                key={b.id}
                batch={b}
                batchOps={opsByBatch.get(b.id) ?? []}
                nodeName={nodeName}
                flash={flash(`batch:${b.id}`)}
                focusId={focusId}
                expanded={expandedBatch === b.id}
                onToggleExpand={() => setExpandedBatch(expandedBatch === b.id ? null : b.id)}
                onOpenNode={onOpenNode}
                onLocate={onLocate}
                onRetry={(id) => doRetryOp.mutate(id)}
              />
            ))}
            {runningOps.map((op) => (
              <OpRow
                key={op.id}
                op={op}
                nodeName={nodeName}
                flash={flash(`op:${op.id}`)}
                focusId={focusId}
                onOpenNode={onOpenNode}
                onLocate={onLocate}
                showTime="created"
              />
            ))}
          </Section>

          <Section title="EN COLA" count={queuedOps.length}>
            {queuedOps.length === 0 && (
              <p style={{ color: t.textFaint, fontSize: 12.5, margin: "0.2rem 0" }}>Cola vacía.</p>
            )}
            {queuedOps.slice(0, 15).map((op) => (
              <OpRow
                key={op.id}
                op={op}
                nodeName={nodeName}
                flash={flash(`op:${op.id}`)}
                focusId={focusId}
                onOpenNode={onOpenNode}
                onLocate={onLocate}
                onCancel={(id) => doCancelOp.mutate(id)}
                showTime="created"
              />
            ))}
            {queuedOps.length > 15 && (
              <p style={{ color: t.textFaint, fontSize: 12 }}>… y {queuedOps.length - 15} más</p>
            )}
          </Section>

          <Section title="REQUIEREN INTERVENCIÓN" count={needsAttention.length}>
            {needsAttention.length === 0 && (
              <p style={{ color: t.textFaint, fontSize: 12.5, margin: "0.2rem 0" }}>
                Nada pendiente de tu intervención.
              </p>
            )}
            {needsAttention.slice(0, 15).map((op) => (
              <OpRow
                key={op.id}
                op={op}
                nodeName={nodeName}
                flash={flash(`op:${op.id}`)}
                focusId={focusId}
                onOpenNode={onOpenNode}
                onLocate={onLocate}
                onRetry={(id) => doRetryOp.mutate(id)}
                showTime="finished"
              />
            ))}
          </Section>
        </div>

        {/* Columna de historial: qué pasó, lotes y sueltas en la misma línea temporal */}
        <div>
          <Section title="HISTORIAL RECIENTE">
            {history.length === 0 && (
              <p style={{ color: t.textFaint, fontSize: 12.5, margin: "0.2rem 0" }}>
                {filtering ? "Nada coincide con los filtros." : "Sin trabajos terminados todavía."}
              </p>
            )}
            {history.map((h) => h.item)}
          </Section>
        </div>
      </div>
    </div>
  );
}

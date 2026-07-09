import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type CSSProperties } from "react";
import {
  cancelBatch,
  createBatch,
  displayName,
  fetchBatch,
  fetchBatchOperations,
  fetchBatches,
  fetchCapabilities,
  fetchConfigSchema,
  pauseBatch,
  previewBatch,
  resumeBatch,
  type BatchPreviewOut,
  type BatchStatus,
  type NodeSummaryOut,
  type OperationOut,
} from "../api/client";
import { styles } from "../styles";

const input: CSSProperties = {
  background: "#0d1117",
  border: "1px solid #30363d",
  color: "#e6edf3",
  borderRadius: 6,
  padding: "0.3rem 0.5rem",
};
const btn: CSSProperties = { ...input, cursor: "pointer" };

const BATCH_STATUS_COLOR: Record<BatchStatus, string> = {
  running: "#1f6feb",
  paused: "#9e6a03",
  cancelled: "#57606a",
  completed: "#1f6f43",
  completed_with_errors: "#b62324",
};

const OP_STATUS_COLOR: Record<string, string> = {
  pending: "#8b949e",
  queued: "#1f4c8f",
  running: "#1f6feb",
  succeeded: "#1f6f43",
  succeeded_unconfirmed: "#8250df",
  verify_failed: "#cf222e",
  failed: "#b62324",
  timeout: "#9e6a03",
  cancelled: "#57606a",
};

function fmtSeconds(s: number | null | undefined): string {
  if (s == null) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}m ${Math.round(s % 60)}s`;
  return `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m`;
}

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `hace ${Math.round(seconds)}s`;
  if (seconds < 3600) return `hace ${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `hace ${Math.round(seconds / 3600)}h`;
  return `hace ${Math.round(seconds / 86400)}d`;
}

function StatusChip({ status }: { status: string }) {
  return (
    <span
      style={{
        background: OP_STATUS_COLOR[status] ?? BATCH_STATUS_COLOR[status as BatchStatus] ?? "#30363d",
        color: "#fff",
        borderRadius: 12,
        padding: "0.1rem 0.6rem",
        fontSize: "0.75rem",
      }}
    >
      {status}
    </span>
  );
}

// ── Asistente de creación (recibe la selección desde la vista Nodos) ─────────

export function BatchWizard({
  selectedIds,
  summaries,
  onDone,
}: {
  selectedIds: string[];
  summaries: NodeSummaryOut[];
  onDone: (batchId: number | null) => void;
}) {
  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: fetchCapabilities, staleTime: 300_000 });
  const schema = useQuery({ queryKey: ["config-schema"], queryFn: fetchConfigSchema, staleTime: 3_600_000 });

  const bulkCaps = (capabilities.data ?? []).filter((c) => c.allow_bulk);
  const [name, setName] = useState("");
  const [opType, setOpType] = useState("metadata.get");
  const [section, setSection] = useState("");
  const [fieldName, setFieldName] = useState("");
  const [fieldValue, setFieldValue] = useState("");
  const [preview, setPreview] = useState<BatchPreviewOut | null>(null);
  const [confirmText, setConfirmText] = useState("");

  const spec = bulkCaps.find((c) => c.operation_type === opType);
  const isConfigSet = opType === "config.set" || opType === "module_config.set";
  const sectionChoices = isConfigSet
    ? (schema.data?.sections ?? [])
        .filter((s) => (opType === "config.set" ? s.kind === "config" : s.kind === "module_config"))
        .map((s) => s.name)
    : spec?.param_choices["section"] ?? [];
  const sectionFields = isConfigSet
    ? (schema.data?.sections ?? []).find((s) => s.name === section)?.fields.filter((f) => f.editable) ?? []
    : [];
  const currentField = sectionFields.find((f) => f.name === fieldName);

  const buildParams = (): Record<string, unknown> => {
    if (isConfigSet) {
      let value: unknown = fieldValue;
      if (currentField?.kind === "int") value = Number.parseInt(fieldValue, 10);
      if (currentField?.kind === "float") value = Number.parseFloat(fieldValue);
      if (currentField?.kind === "bool") value = fieldValue === "true";
      return { section, values: { [fieldName]: value } };
    }
    if (sectionChoices.length > 0) return { section };
    return {};
  };

  const paramsReady = isConfigSet
    ? section !== "" && fieldName !== "" && fieldValue !== ""
    : sectionChoices.length === 0 || section !== "";

  const doPreview = useMutation({
    mutationFn: () =>
      previewBatch({ operation_type: opType, params: buildParams(), scope: { node_ids: selectedIds } }),
    onSuccess: setPreview,
  });
  const doCreate = useMutation({
    mutationFn: () =>
      createBatch({
        name: name || `${opType} × ${preview?.eligible_count ?? 0}`,
        operation_type: opType,
        params: buildParams(),
        node_ids: (preview?.eligible ?? []).map((n) => n.node_id),
        scope_description: preview?.scope_description,
      }),
    onSuccess: (batch) => onDone(batch.id),
  });

  const nodeName = (id: string) => {
    const s = summaries.find((x) => x.node.node_id === id);
    return s ? displayName(s.node) : id;
  };

  return (
    <div style={styles.card}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0 }}>Nuevo batch — {selectedIds.length} nodos seleccionados</h2>
        <button style={btn} onClick={() => onDone(null)}>✕</button>
      </div>

      {/* Paso 1: operación y parámetros */}
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center", marginTop: "0.6rem" }}>
        <input
          style={{ ...input, minWidth: 200 }}
          placeholder="Nombre del batch"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <select
          style={input}
          value={opType}
          onChange={(e) => {
            setOpType(e.target.value);
            setSection("");
            setFieldName("");
            setFieldValue("");
            setPreview(null);
          }}
        >
          {bulkCaps.map((c) => (
            <option key={c.operation_type} value={c.operation_type}>
              {c.kind === "set" ? "✏️ " : ""}{c.operation_type} — {c.description}
            </option>
          ))}
        </select>
        {sectionChoices.length > 0 && (
          <select
            style={input}
            value={section}
            onChange={(e) => { setSection(e.target.value); setFieldName(""); setPreview(null); }}
          >
            <option value="">— sección —</option>
            {sectionChoices.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        )}
        {isConfigSet && section && (
          <>
            <select
              style={input}
              value={fieldName}
              onChange={(e) => { setFieldName(e.target.value); setFieldValue(""); setPreview(null); }}
            >
              <option value="">— campo —</option>
              {sectionFields.map((f) => (
                <option key={f.name} value={f.name}>{f.name} ({f.kind})</option>
              ))}
            </select>
            {currentField?.kind === "enum" ? (
              <select style={input} value={fieldValue} onChange={(e) => setFieldValue(e.target.value)}>
                <option value="">— valor —</option>
                {currentField.enum_values.map((v) => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            ) : currentField?.kind === "bool" ? (
              <select style={input} value={fieldValue} onChange={(e) => setFieldValue(e.target.value)}>
                <option value="">— valor —</option>
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
            ) : (
              <input
                style={input}
                type={currentField?.kind === "int" || currentField?.kind === "float" ? "number" : "text"}
                placeholder="valor"
                value={fieldValue}
                onChange={(e) => setFieldValue(e.target.value)}
              />
            )}
          </>
        )}
        <button
          style={btn}
          disabled={!paramsReady || selectedIds.length === 0 || doPreview.isPending}
          onClick={() => doPreview.mutate()}
        >
          Simular
        </button>
      </div>
      {doPreview.isError && <p style={styles.bad}>{String(doPreview.error)}</p>}

      {/* Paso 2: vista previa */}
      {preview && (
        <div style={{ border: "1px solid #30363d", borderRadius: 8, padding: "0.8rem", marginTop: "0.8rem" }}>
          <h3 style={{ marginTop: 0 }}>Simulación (no modifica nada)</h3>
          <div style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap" }}>
            <span>Seleccionados: <strong>{preview.total_selected}</strong></span>
            <span style={styles.ok}>Elegibles: <strong>{preview.eligible_count}</strong></span>
            <span style={preview.excluded_count ? styles.bad : styles.dim}>
              Excluidos: <strong>{preview.excluded_count}</strong>
            </span>
            <span>Verificación: {preview.requires_verification ? "sí (read-back por nodo)" : "no (lectura)"}</span>
            <span>Duración estimada: <strong>{fmtSeconds(preview.estimated_seconds)}</strong></span>
          </div>
          {preview.excluded.length > 0 && (
            <div style={{ marginTop: "0.5rem" }}>
              <strong style={styles.bad}>Excluidos:</strong>
              <ul style={{ margin: "0.2rem 0" }}>
                {preview.excluded.map((n) => (
                  <li key={n.node_id} style={styles.mono}>
                    {nodeName(n.node_id)} — {n.blockers.join("; ")}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {preview.eligible.some((n) => n.warnings.length > 0) && (
            <div style={{ marginTop: "0.5rem" }}>
              <strong style={{ color: "#d29922" }}>Advertencias:</strong>
              <ul style={{ margin: "0.2rem 0" }}>
                {preview.eligible
                  .filter((n) => n.warnings.length > 0)
                  .map((n) => (
                    <li key={n.node_id} style={styles.mono}>
                      {nodeName(n.node_id)} — {n.warnings.join("; ")}
                    </li>
                  ))}
              </ul>
            </div>
          )}

          {/* Paso 3: confirmación */}
          <p style={styles.dim}>
            Escribe <span style={styles.mono}>CONFIRMAR</span> para ejecutar el batch sobre{" "}
            <strong>{preview.eligible_count}</strong> nodos:
          </p>
          <input style={input} value={confirmText} onChange={(e) => setConfirmText(e.target.value)} />
          <button
            style={{ ...btn, marginLeft: 8, background: confirmText === "CONFIRMAR" ? "#1f6feb" : "transparent" }}
            disabled={confirmText !== "CONFIRMAR" || preview.eligible_count === 0 || doCreate.isPending}
            onClick={() => doCreate.mutate()}
          >
            Ejecutar batch
          </button>
          {doCreate.isError && <p style={styles.bad}>{String(doCreate.error)}</p>}
        </div>
      )}
    </div>
  );
}

// ── Monitor de un batch ──────────────────────────────────────────────────────

function BatchMonitor({
  batchId,
  summaries,
  onBack,
}: {
  batchId: number;
  summaries: NodeSummaryOut[];
  onBack: () => void;
}) {
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ["batch", batchId],
    queryFn: () => fetchBatch(batchId),
    refetchInterval: 3_000,
  });
  const [opStatusFilter, setOpStatusFilter] = useState("");
  const ops = useQuery({
    queryKey: ["batch-ops", batchId, opStatusFilter],
    queryFn: () => fetchBatchOperations(batchId, opStatusFilter || undefined),
    refetchInterval: 5_000,
  });
  const [expanded, setExpanded] = useState<number | null>(null);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["batch", batchId] });
    queryClient.invalidateQueries({ queryKey: ["batches"] });
  };
  const pause = useMutation({ mutationFn: () => pauseBatch(batchId), onSettled: invalidate });
  const resume = useMutation({ mutationFn: () => resumeBatch(batchId), onSettled: invalidate });
  const cancel = useMutation({ mutationFn: () => cancelBatch(batchId), onSettled: invalidate });
  const [cancelArmed, setCancelArmed] = useState(false);

  const nodeName = (id: string) => {
    const s = summaries.find((x) => x.node.node_id === id);
    return s ? displayName(s.node) : id;
  };

  if (detail.isLoading || !detail.data) return <div style={styles.card}>Cargando batch #{batchId}…</div>;
  const b = detail.data;
  const p = b.progress;

  return (
    <div>
      <div style={styles.card}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.8rem", flexWrap: "wrap" }}>
          <button style={btn} onClick={onBack}>← Historial</button>
          <h2 style={{ margin: 0 }}>#{b.id} {b.name}</h2>
          <StatusChip status={b.status} />
          <span style={{ ...styles.mono, ...styles.dim }}>
            {b.operation_type}
            {typeof b.params.section === "string" ? `:${b.params.section}` : ""}
          </span>
          <span style={{ marginLeft: "auto", display: "flex", gap: "0.4rem" }}>
            {b.status === "running" && (
              <button style={btn} onClick={() => pause.mutate()}>⏸ Pausar</button>
            )}
            {b.status === "paused" && (
              <button style={btn} onClick={() => resume.mutate()}>▶ Reanudar</button>
            )}
            {(b.status === "running" || b.status === "paused") &&
              (cancelArmed ? (
                <button
                  style={{ ...btn, background: "#b62324" }}
                  onClick={() => { cancel.mutate(); setCancelArmed(false); }}
                >
                  ¿Cancelar {p.counts["pending"] ?? 0} pendientes?
                </button>
              ) : (
                <button style={btn} onClick={() => setCancelArmed(true)}>✕ Cancelar</button>
              ))}
          </span>
        </div>

        {/* Barra de progreso */}
        <div style={{ background: "#21262d", borderRadius: 8, height: 22, marginTop: "0.8rem", overflow: "hidden" }}>
          <div
            style={{
              width: `${p.percent}%`,
              height: "100%",
              background: b.status === "completed_with_errors" ? "#b62324" : "#1f6f43",
              transition: "width 0.5s",
            }}
          />
        </div>
        <div style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
          <span><strong>{p.percent}%</strong> ({p.done}/{p.total})</span>
          <span>Procesando: {p.current_node_id ? <span style={styles.mono}>{nodeName(p.current_node_id)}</span> : "—"}</span>
          <span>Velocidad: {p.rate_per_minute != null ? `${p.rate_per_minute} ops/min` : "—"}</span>
          <span>ETA: {b.status === "running" ? fmtSeconds(p.eta_seconds) : "—"}</span>
          <span>Transcurrido: {fmtSeconds(p.elapsed_seconds)}</span>
        </div>
        <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
          {Object.entries(p.counts).map(([status, count]) => (
            <button
              key={status}
              style={{ ...btn, borderColor: opStatusFilter === status ? "#e3b341" : "#30363d", fontSize: "0.8rem" }}
              onClick={() => setOpStatusFilter(opStatusFilter === status ? "" : status)}
            >
              <StatusChip status={status} /> {count}
            </button>
          ))}
        </div>
      </div>

      <div style={styles.card}>
        <h3 style={{ marginTop: 0 }}>
          Nodos del batch {opStatusFilter && <span style={styles.dim}>(filtro: {opStatusFilter})</span>}
        </h3>
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>Nodo</th>
              <th style={styles.th}>Estado</th>
              <th style={styles.th}>Intentos</th>
              <th style={styles.th}>Duración</th>
              <th style={styles.th}>Error</th>
            </tr>
          </thead>
          <tbody>
            {(ops.data ?? []).map((op: OperationOut) => (
              <>
                <tr
                  key={op.id}
                  style={{ cursor: "pointer" }}
                  onClick={() => setExpanded(expanded === op.id ? null : op.id)}
                >
                  <td style={{ ...styles.td, ...styles.mono }}>{nodeName(op.target_node_id)}</td>
                  <td style={styles.td}><StatusChip status={op.status} /></td>
                  <td style={styles.td}>{op.attempts}/{op.max_attempts}</td>
                  <td style={styles.td}>{op.duration_ms != null ? `${op.duration_ms} ms` : "—"}</td>
                  <td style={{ ...styles.td, ...styles.dim }}>{op.error ?? ""}</td>
                </tr>
                {expanded === op.id && (
                  <tr key={`${op.id}-d`}>
                    <td style={styles.td} colSpan={5}>
                      <pre style={{ ...styles.mono, whiteSpace: "pre-wrap", margin: 0 }}>
                        {JSON.stringify(op.result ?? op.params, null, 2)}
                      </pre>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Vista principal: historial + monitor ─────────────────────────────────────

export function BatchesView({
  summaries,
  openBatchId,
  onOpenBatch,
}: {
  summaries: NodeSummaryOut[];
  openBatchId: number | null;
  onOpenBatch: (id: number | null) => void;
}) {
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const batches = useQuery({
    queryKey: ["batches", statusFilter, typeFilter],
    queryFn: () => fetchBatches({ status: statusFilter || undefined, operation_type: typeFilter || undefined }),
    refetchInterval: 10_000,
  });
  const types = useMemo(
    () => [...new Set((batches.data ?? []).map((b) => b.operation_type))].sort(),
    [batches.data],
  );

  if (openBatchId != null) {
    return <BatchMonitor batchId={openBatchId} summaries={summaries} onBack={() => onOpenBatch(null)} />;
  }

  return (
    <div style={styles.card}>
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
        <h2 style={{ margin: 0 }}>Batches</h2>
        <select style={input} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">estado</option>
          {["running", "paused", "cancelled", "completed", "completed_with_errors"].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select style={input} value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
          <option value="">tipo</option>
          {types.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <span style={{ ...styles.dim, marginLeft: "auto", fontSize: "0.85rem" }}>
          Para crear un batch: vista Nodos → seleccionar → “Crear batch”
        </span>
      </div>
      {(batches.data ?? []).length === 0 && (
        <p style={styles.dim}>Sin batches todavía.</p>
      )}
      {(batches.data ?? []).length > 0 && (
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>#</th>
              <th style={styles.th}>Nombre</th>
              <th style={styles.th}>Operación</th>
              <th style={styles.th}>Nodos</th>
              <th style={styles.th}>Estado</th>
              <th style={styles.th}>Usuario</th>
              <th style={styles.th}>Creado</th>
            </tr>
          </thead>
          <tbody>
            {(batches.data ?? []).map((b) => (
              <tr key={b.id} style={{ cursor: "pointer" }} onClick={() => onOpenBatch(b.id)}>
                <td style={styles.td}>{b.id}</td>
                <td style={styles.td}>{b.name}</td>
                <td style={{ ...styles.td, ...styles.mono }}>
                  {b.operation_type}
                  {typeof b.params.section === "string" ? `:${b.params.section}` : ""}
                </td>
                <td style={styles.td}>{b.node_count}</td>
                <td style={styles.td}><StatusChip status={b.status} /></td>
                <td style={styles.td}>{b.created_by}</td>
                <td style={styles.td}>{relativeTime(b.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

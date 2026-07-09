import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type CSSProperties } from "react";
import {
  cancelOperation,
  createOperation,
  displayName,
  fetchCapabilities,
  fetchOperations,
  retryOperation,
  type NodeSummaryOut,
  type OperationOut,
  type OperationStatus,
} from "../api/client";
import { styles } from "../styles";

const STATUS_COLOR: Record<OperationStatus, string> = {
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

const STATUS_LABEL: Partial<Record<OperationStatus, string>> = {
  succeeded: "confirmada",
  succeeded_unconfirmed: "sin confirmar",
  verify_failed: "verificación fallida",
};

const input: CSSProperties = {
  background: "#0d1117",
  border: "1px solid #30363d",
  color: "#e6edf3",
  borderRadius: 6,
  padding: "0.3rem 0.5rem",
};

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `hace ${Math.round(seconds)}s`;
  if (seconds < 3600) return `hace ${Math.round(seconds / 60)}m`;
  return `hace ${Math.round(seconds / 3600)}h`;
}

function VerifyDetail({ result }: { result: Record<string, unknown> }) {
  const blocks: [string, unknown][] = [
    ["Valor anterior", result.previous],
    ["Valor solicitado", result.requested],
    ["Valor leído en la verificación", result.verified],
  ];
  return (
    <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
      {blocks.map(([label, value]) => (
        <div key={label} style={{ flex: "1 1 200px" }}>
          <div style={{ ...styles.dim, fontSize: "0.8rem" }}>{label}</div>
          <pre style={{ ...styles.mono, whiteSpace: "pre-wrap", margin: 0 }}>
            {value == null ? "— no disponible —" : JSON.stringify(value, null, 2)}
          </pre>
        </div>
      ))}
    </div>
  );
}

export function OperationsView({ summaries }: { summaries: NodeSummaryOut[] }) {
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["operations"] });

  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: fetchCapabilities, staleTime: 300_000 });
  const operations = useQuery({
    queryKey: ["operations"],
    queryFn: () => fetchOperations(undefined, 100),
    refetchInterval: 10_000,
  });

  const create = useMutation({ mutationFn: createOperation, onSettled: invalidate });
  const cancel = useMutation({ mutationFn: cancelOperation, onSettled: invalidate });
  const retry = useMutation({ mutationFn: retryOperation, onSettled: invalidate });

  const [nodeId, setNodeId] = useState("");
  const [opType, setOpType] = useState("metadata.get");
  const [section, setSection] = useState("");
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);

  const spec = useMemo(
    () => (capabilities.data ?? []).find((c) => c.operation_type === opType),
    [capabilities.data, opType],
  );
  const sections = spec?.param_choices["section"] ?? [];
  const paramFields = spec?.param_fields ?? [];

  const buildParams = (): Record<string, unknown> => {
    if (sections.length > 0) return { section };
    const params: Record<string, unknown> = {};
    for (const f of paramFields) {
      const raw = fieldValues[f.name]?.trim();
      if (raw === undefined || raw === "") continue;
      params[f.name] = f.kind === "number" ? Number(raw) : raw;
    }
    return params;
  };

  const paramsReady =
    sections.length > 0
      ? section !== ""
      : paramFields.every((f) => !f.required || (fieldValues[f.name] ?? "").trim() !== "") &&
        (paramFields.length === 0 || Object.keys(buildParams()).length > 0);
  const canSubmit = nodeId !== "" && paramsReady;

  const submit = () => {
    create.mutate({ node_id: nodeId, operation_type: opType, params: buildParams() });
    setConfirming(false);
    setConfirmText("");
  };

  const resetOp = (type: string) => {
    setOpType(type);
    setSection("");
    setFieldValues({});
    setConfirming(false);
    setConfirmText("");
  };

  const nodeName = (id: string) => {
    const s = summaries.find((x) => x.node.node_id === id);
    return s ? displayName(s.node) : id;
  };

  return (
    <div>
      <div style={styles.card}>
        <h2 style={{ marginTop: 0 }}>Nueva operación remota</h2>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
          <select style={input} value={nodeId} onChange={(e) => { setNodeId(e.target.value); setConfirming(false); }}>
            <option value="">— nodo —</option>
            {summaries.map((s) => (
              <option key={s.node.node_id} value={s.node.node_id}>
                {displayName(s.node)} {s.node.online ? "· online" : "· offline"}
              </option>
            ))}
          </select>
          <select style={input} value={opType} onChange={(e) => resetOp(e.target.value)}>
            {(capabilities.data ?? []).map((c) => (
              <option key={c.operation_type} value={c.operation_type}>
                {c.kind === "set" ? "✏️ " : ""}{c.operation_type} — {c.description}
              </option>
            ))}
          </select>
          {sections.length > 0 && (
            <select style={input} value={section} onChange={(e) => setSection(e.target.value)}>
              <option value="">— sección —</option>
              {sections.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          )}
          {paramFields.map((f) => (
            <input
              key={f.name}
              style={{ ...input, width: f.kind === "number" ? 110 : 160 }}
              type={f.kind === "number" ? "number" : "text"}
              placeholder={f.name + (f.required ? " *" : "")}
              maxLength={f.max_length ?? undefined}
              min={f.minimum ?? undefined}
              max={f.maximum ?? undefined}
              value={fieldValues[f.name] ?? ""}
              onChange={(e) => {
                setFieldValues({ ...fieldValues, [f.name]: e.target.value });
                setConfirming(false);
              }}
            />
          ))}
          {!spec?.requires_confirmation ? (
            <button
              style={{ ...input, cursor: canSubmit ? "pointer" : "not-allowed" }}
              disabled={!canSubmit || create.isPending}
              onClick={submit}
            >
              Añadir a la cola
            </button>
          ) : (
            <button
              style={{ ...input, cursor: canSubmit ? "pointer" : "not-allowed" }}
              disabled={!canSubmit || create.isPending}
              onClick={() => setConfirming(true)}
            >
              Revisar y confirmar…
            </button>
          )}
        </div>

        {/* Confirmación explícita para operaciones de escritura (M1.3) */}
        {confirming && spec?.requires_confirmation && (
          <div style={{ border: "1px solid #9e6a03", borderRadius: 8, padding: "0.8rem", marginTop: "0.8rem" }}>
            <p style={{ marginTop: 0 }}>
              ⚠️ Vas a <strong>modificar</strong> el nodo <strong>{nodeName(nodeId)}</strong> con{" "}
              <span style={styles.mono}>{opType}</span> y parámetros{" "}
              <span style={styles.mono}>{JSON.stringify(buildParams())}</span>.{" "}
              {spec?.ack_only
                ? "Tras el envío se comprobará el ACK/NAK del firmware — el dispositivo no permite releer este valor para verificarlo."
                : "Tras el envío se hará una lectura de verificación automática."}
            </p>
            <p style={styles.dim}>
              Escribe el ID del nodo (<span style={styles.mono}>{nodeId}</span>) para confirmar:
            </p>
            <input
              style={{ ...input, width: 160 }}
              placeholder={nodeId}
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
            />
            <button
              style={{ ...input, marginLeft: 8, cursor: confirmText === nodeId ? "pointer" : "not-allowed" }}
              disabled={confirmText !== nodeId || create.isPending}
              onClick={submit}
            >
              Confirmar y añadir a la cola
            </button>
            <button
              style={{ ...input, marginLeft: 8 }}
              onClick={() => { setConfirming(false); setConfirmText(""); }}
            >
              Cancelar
            </button>
          </div>
        )}

        {create.isError && <p style={styles.bad}>{String(create.error)}</p>}
        <p style={{ ...styles.dim, fontSize: "0.8rem" }}>
          Las operaciones respetan el presupuesto de malla (rate limit global y 1 en vuelo por
          pasarela). En escrituras: <strong>succeeded</strong> = cambio confirmado por lectura
          posterior · <strong>sin confirmar</strong> = comando enviado pero la verificación no pudo
          leerse · <strong>verificación fallida</strong> = la lectura posterior no coincide con lo
          solicitado.
        </p>
      </div>

      <div style={styles.card}>
        <h2 style={{ marginTop: 0 }}>Cola e historial</h2>
        {operations.isLoading && <p>Cargando…</p>}
        {(operations.data ?? []).length === 0 && !operations.isLoading && (
          <p style={styles.dim}>Sin operaciones todavía.</p>
        )}
        {(operations.data ?? []).length > 0 && (
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>#</th>
                <th style={styles.th}>Nodo</th>
                <th style={styles.th}>Operación</th>
                <th style={styles.th}>Estado</th>
                <th style={styles.th}>Intentos</th>
                <th style={styles.th}>Duración</th>
                <th style={styles.th}>Creada</th>
                <th style={styles.th}></th>
              </tr>
            </thead>
            <tbody>
              {(operations.data ?? []).map((op: OperationOut) => (
                <>
                  <tr
                    key={op.id}
                    style={{ cursor: "pointer" }}
                    onClick={() => setExpanded(expanded === op.id ? null : op.id)}
                  >
                    <td style={styles.td}>{op.id}</td>
                    <td style={{ ...styles.td, ...styles.mono }}>{nodeName(op.target_node_id)}</td>
                    <td style={{ ...styles.td, ...styles.mono }}>
                      {op.operation_type}
                      {typeof op.params.section === "string" ? `:${op.params.section}` : ""}
                    </td>
                    <td style={styles.td}>
                      <span
                        style={{
                          background: STATUS_COLOR[op.status],
                          color: "#fff",
                          borderRadius: 12,
                          padding: "0.1rem 0.6rem",
                          fontSize: "0.75rem",
                        }}
                        title={STATUS_LABEL[op.status]}
                      >
                        {op.status}
                      </span>
                    </td>
                    <td style={styles.td}>
                      {op.attempts}/{op.max_attempts}
                    </td>
                    <td style={styles.td}>{op.duration_ms != null ? `${op.duration_ms} ms` : "—"}</td>
                    <td style={styles.td}>{relativeTime(op.created_at)}</td>
                    <td style={styles.td}>
                      {(op.status === "pending" || op.status === "queued") && (
                        <button style={input} onClick={(e) => { e.stopPropagation(); cancel.mutate(op.id); }}>
                          Cancelar
                        </button>
                      )}
                      {(op.status === "failed" || op.status === "timeout" || op.status === "cancelled") && (
                        <button style={input} onClick={(e) => { e.stopPropagation(); retry.mutate(op.id); }}>
                          Reintentar
                        </button>
                      )}
                    </td>
                  </tr>
                  {expanded === op.id && (
                    <tr key={`${op.id}-detail`}>
                      <td style={styles.td} colSpan={8}>
                        {op.error && <p style={styles.bad}>Error: {op.error}</p>}
                        {op.result && "verify" in op.result ? (
                          <VerifyDetail result={op.result} />
                        ) : (
                          <pre style={{ ...styles.mono, whiteSpace: "pre-wrap", margin: 0 }}>
                            {JSON.stringify(op.result ?? op.params, null, 2)}
                          </pre>
                        )}
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

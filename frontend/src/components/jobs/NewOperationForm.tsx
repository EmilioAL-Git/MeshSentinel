import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type CSSProperties } from "react";
import {
  createOperation,
  displayName,
  fetchCapabilities,
  type NodeSummaryOut,
} from "../../api/client";
import { trackOperations } from "../../opTracker";
import { t } from "../../tokens";
import { NodeSelect } from "../NodeSelect";
import { toast } from "../shell/Toast";

// Creación de una operación individual (M1.1/M1.3), portada de la antigua
// vista Operaciones al Centro de Trabajos. Los GETs se encolan directos;
// los SETs mantienen su confirmación explícita tecleando el node_id.

const input: CSSProperties = {
  background: t.bg,
  border: `1px solid ${t.border}`,
  color: t.text,
  borderRadius: 6,
  padding: "0.3rem 0.5rem",
  fontSize: 12.5,
};

export function NewOperationForm({
  summaries,
  onClose,
}: {
  summaries: NodeSummaryOut[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: fetchCapabilities, staleTime: 300_000 });

  const create = useMutation({
    mutationFn: createOperation,
    onSuccess: (op) => {
      trackOperations([op.id]);
      toast(`${op.operation_type} añadida a la cola (op #${op.id})`);
      onClose();
    },
    onError: (e) => toast(`No se pudo encolar: ${e.message}`, { kind: "error" }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["operations"] }),
  });

  const [nodeId, setNodeId] = useState("");
  const [opType, setOpType] = useState("metadata.get");
  const [section, setSection] = useState("");
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState(false);
  const [confirmText, setConfirmText] = useState("");

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
    <div
      style={{
        background: t.surface,
        border: `1px solid ${t.border}`,
        borderRadius: 6,
        padding: "0.7rem 0.9rem",
        marginBottom: "0.8rem",
      }}
    >
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
        <span style={{ color: t.textDim, fontSize: 11, letterSpacing: "0.07em", fontWeight: 600 }}>
          NUEVA OPERACIÓN
        </span>
        <NodeSelect
          value={nodeId}
          onChange={(id) => { setNodeId(id); setConfirming(false); }}
          options={summaries}
          showOnlineStatus
        />
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
        {paramFields.map((f) =>
          f.name === "subject_node_id" ? (
            <NodeSelect
              key={f.name}
              value={fieldValues[f.name] ?? ""}
              onChange={(id) => {
                setFieldValues({ ...fieldValues, [f.name]: id });
                setConfirming(false);
              }}
              options={summaries.filter((s) => s.node.node_id !== nodeId)}
              placeholder="— nodo sujeto —"
            />
          ) : (
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
          ),
        )}
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
        <button
          style={{ ...input, cursor: "pointer", marginLeft: "auto" }}
          onClick={onClose}
          title="Cerrar"
        >
          ✕
        </button>
      </div>

      {/* Confirmación explícita para operaciones de escritura (M1.3) */}
      {confirming && spec?.requires_confirmation && (
        <div style={{ border: `1px solid ${t.warn}`, borderRadius: 6, padding: "0.7rem", marginTop: "0.7rem", fontSize: 12.5 }}>
          <p style={{ marginTop: 0 }}>
            ⚠️ Vas a <strong>modificar</strong> el nodo <strong>{nodeName(nodeId)}</strong> con{" "}
            <span style={{ fontFamily: t.fontMono }}>{opType}</span> y parámetros{" "}
            <span style={{ fontFamily: t.fontMono }}>{JSON.stringify(buildParams())}</span>.{" "}
            {spec?.ack_only
              ? "Tras el envío se comprobará el ACK/NAK del firmware — el dispositivo no permite releer este valor para verificarlo."
              : "Tras el envío se hará una lectura de verificación automática."}
          </p>
          <p style={{ color: t.textDim }}>
            Escribe el ID del nodo (<span style={{ fontFamily: t.fontMono }}>{nodeId}</span>) para confirmar:
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
            style={{ ...input, marginLeft: 8, cursor: "pointer" }}
            onClick={() => { setConfirming(false); setConfirmText(""); }}
          >
            Cancelar
          </button>
        </div>
      )}
    </div>
  );
}

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type CSSProperties } from "react";
import {
  createBatch,
  displayName,
  fetchCapabilities,
  fetchConfigSchema,
  fetchGateways,
  GATEWAY_SELECTION_PREFERRED,
  previewBatch,
  type BatchPreviewOut,
  type GatewaySelectionIn,
  type NodeSummaryOut,
} from "../../api/client";
import { styles } from "../../styles";
import { GatewaySelect } from "../shell/GatewaySelect";
import { NodeSelect } from "../NodeSelect";
import { fmtSeconds } from "./status";

// Asistente de creación de lotes (M2): recibe la selección desde la vista
// Nodos. El flujo simular → CONFIRMAR → ejecutar es una decisión de
// seguridad (ADR 0016) y no se acorta. Movido de BatchesView en v0.7.4.

const input: CSSProperties = {
  background: "var(--bg)",
  border: "1px solid var(--border)",
  color: "var(--text)",
  borderRadius: 6,
  padding: "0.3rem 0.5rem",
};
const btn: CSSProperties = { ...input, cursor: "pointer" };

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
  // Mismo queryKey que App.tsx: caché compartida, sin fetch nuevo.
  const gateways = useQuery({ queryKey: ["gateways"], queryFn: () => fetchGateways() });

  const bulkCaps = (capabilities.data ?? []).filter((c) => c.allow_bulk);
  const [name, setName] = useState("");
  const [opType, setOpType] = useState("metadata.get");
  const [section, setSection] = useState("");
  const [fieldName, setFieldName] = useState("");
  const [fieldValue, setFieldValue] = useState("");
  const [otherFieldValues, setOtherFieldValues] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<BatchPreviewOut | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [gatewaySelection, setGatewaySelection] = useState<GatewaySelectionIn>(GATEWAY_SELECTION_PREFERRED);

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
  const paramFields = !isConfigSet && sectionChoices.length === 0 ? spec?.param_fields ?? [] : [];

  const buildParams = (): Record<string, unknown> => {
    if (isConfigSet) {
      let value: unknown = fieldValue;
      if (currentField?.kind === "int") value = Number.parseInt(fieldValue, 10);
      if (currentField?.kind === "float") value = Number.parseFloat(fieldValue);
      if (currentField?.kind === "bool") value = fieldValue === "true";
      return { section, values: { [fieldName]: value } };
    }
    if (sectionChoices.length > 0) return { section };
    const params: Record<string, unknown> = {};
    for (const f of paramFields) {
      const raw = otherFieldValues[f.name]?.trim();
      if (raw === undefined || raw === "") continue;
      params[f.name] = f.kind === "number" ? Number(raw) : raw;
    }
    return params;
  };

  const paramsReady = isConfigSet
    ? section !== "" && fieldName !== "" && fieldValue !== ""
    : sectionChoices.length > 0
      ? section !== ""
      : paramFields.every((f) => !f.required || (otherFieldValues[f.name] ?? "").trim() !== "");

  const doPreview = useMutation({
    mutationFn: () =>
      previewBatch({ operation_type: opType, params: buildParams(), scope: { node_ids: selectedIds } }),
    onSuccess: setPreview,
  });
  const doCreate = useMutation({
    mutationFn: () => {
      const excludedIds = new Set((preview?.excluded ?? []).map((n) => n.node_id));
      return createBatch({
        name: name || `${opType} × ${preview?.eligible_count ?? 0}`,
        operation_type: opType,
        params: buildParams(),
        node_ids: selectedIds.filter((id) => !excludedIds.has(id)),
        scope_description: preview?.scope_description,
        gateway_selection: gatewaySelection,
      });
    },
    onSuccess: (batch) => onDone(batch.id),
  });

  const nodeName = (id: string) => {
    const s = summaries.find((x) => x.node.node_id === id);
    return s ? displayName(s.node) : id;
  };

  return (
    <div style={styles.card}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0 }}>Nuevo lote — {selectedIds.length} nodos seleccionados</h2>
        <button style={btn} onClick={() => onDone(null)}>✕</button>
      </div>

      {/* Paso 1: operación y parámetros */}
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center", marginTop: "0.6rem" }}>
        <input
          style={{ ...input, minWidth: 200 }}
          placeholder="Nombre del lote"
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
            setOtherFieldValues({});
            setPreview(null);
          }}
        >
          {bulkCaps.map((c) => (
            <option key={c.operation_type} value={c.operation_type}>
              {c.kind === "set" ? "✏️ " : ""}{c.operation_type} — {c.description}
            </option>
          ))}
        </select>
        {paramFields.map((f) =>
          f.name === "subject_node_id" ? (
            <NodeSelect
              key={f.name}
              value={otherFieldValues[f.name] ?? ""}
              onChange={(id) => { setOtherFieldValues({ ...otherFieldValues, [f.name]: id }); setPreview(null); }}
              options={summaries}
              placeholder="— nodo sujeto —"
            />
          ) : (
            <input
              key={f.name}
              style={input}
              type={f.kind === "number" ? "number" : "text"}
              placeholder={f.name + (f.required ? " *" : "")}
              value={otherFieldValues[f.name] ?? ""}
              onChange={(e) => { setOtherFieldValues({ ...otherFieldValues, [f.name]: e.target.value }); setPreview(null); }}
            />
          ),
        )}
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
        <GatewaySelect value={gatewaySelection} onChange={setGatewaySelection} gateways={gateways.data ?? []} />
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
        <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.8rem", marginTop: "0.8rem" }}>
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
              <strong style={{ color: "var(--warn)" }}>Advertencias:</strong>
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
            Escribe <span style={styles.mono}>CONFIRMAR</span> para ejecutar el lote sobre{" "}
            <strong>{preview.eligible_count}</strong> nodos:
          </p>
          <input style={input} value={confirmText} onChange={(e) => setConfirmText(e.target.value)} />
          <button
            style={{ ...btn, marginLeft: 8, background: confirmText === "CONFIRMAR" ? "var(--accent)" : "transparent" }}
            disabled={confirmText !== "CONFIRMAR" || preview.eligible_count === 0 || doCreate.isPending}
            onClick={() => doCreate.mutate()}
          >
            Ejecutar lote
          </button>
          {doCreate.isError && <p style={styles.bad}>{String(doCreate.error)}</p>}
        </div>
      )}
    </div>
  );
}

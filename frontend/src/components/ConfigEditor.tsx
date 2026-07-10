import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  applyNodeConfig,
  fetchConfigSchema,
  fetchNodeConfig,
  fetchOperations,
  refreshNodeConfig,
  type ConfigFieldSchema,
  type ConfigSchemaOut,
  type ConfigSectionSchema,
  type NodeSummaryOut,
  type SectionSnapshot,
} from "../api/client";
import { NodeSelect } from "./NodeSelect";
import { styles } from "../styles";

interface Props {
  summaries: NodeSummaryOut[];
}

export const RISK_STYLE: Record<string, CSSProperties> = {
  SAFE: { background: "var(--ok-tint)", color: "var(--ok)", border: "1px solid var(--ok)" },
  WARNING: { background: "var(--warn-tint)", color: "var(--warn)", border: "1px solid var(--warn)" },
  DANGEROUS: { background: "var(--crit-tint)", color: "var(--crit)", border: "1px solid var(--crit)" },
};

const input: CSSProperties = {
  background: "var(--bg)",
  border: "1px solid var(--border)",
  color: "var(--text)",
  borderRadius: 6,
  padding: "0.3rem 0.5rem",
  minWidth: 180,
};

const btn: CSSProperties = { ...input, minWidth: 0, cursor: "pointer" };

function snakeToCamel(name: string): string {
  return name.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
}

export function readCurrentValue(current: Record<string, unknown>, fieldName: string): unknown {
  if (fieldName in current) return current[fieldName];
  const camel = snakeToCamel(fieldName);
  return camel in current ? current[camel] : undefined;
}

export function displayValue(value: unknown): string {
  if (value === undefined || value === null) return "—";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function coerceValue(field: ConfigFieldSchema, raw: string): unknown {
  if (field.kind === "bool") return raw === "true";
  if (field.kind === "int") return raw === "" ? 0 : Number.parseInt(raw, 10);
  if (field.kind === "float") return raw === "" ? 0 : Number.parseFloat(raw);
  if (field.kind === "enum") return raw;
  return raw;
}

/** Convierte el valor pintado en el input (siempre string) a algo comparable
 * con el valor actual del snapshot. Devuelve null si el campo está vacío. */
function normalizeInputForCompare(field: ConfigFieldSchema, raw: string): unknown {
  if (raw === "") return null;
  return coerceValue(field, raw);
}

function equalValues(a: unknown, b: unknown): boolean {
  if (a === null || a === undefined) return b === null || b === undefined || b === "";
  if (typeof a === "number" && typeof b === "string") return String(a) === b;
  if (typeof a === "boolean" && typeof b === "string") return String(a) === b;
  return a === b;
}

export function FieldControl({
  field,
  currentValue,
  editedRaw,
  onChange,
  placeholder,
}: {
  field: ConfigFieldSchema;
  currentValue: unknown;
  editedRaw: string | undefined;
  onChange: (raw: string) => void;
  placeholder?: string;
}) {
  if (!field.editable) {
    return (
      <span style={{ ...styles.dim, fontStyle: "italic" }}>
        {field.repeated ? "repetido" : "no editable en el editor genérico"}
      </span>
    );
  }
  const value = editedRaw ?? "";
  const emptyLabel = placeholder ?? "— sin cambio —";
  if (field.kind === "enum") {
    return (
      <select style={input} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{emptyLabel}</option>
        {field.enum_values.map((ev) => (
          <option key={ev} value={ev}>
            {ev}
          </option>
        ))}
      </select>
    );
  }
  if (field.kind === "bool") {
    return (
      <select style={input} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{emptyLabel}</option>
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    );
  }
  if (field.kind === "int" || field.kind === "float") {
    return (
      <input
        style={input}
        type="number"
        step={field.kind === "float" ? "any" : 1}
        placeholder={placeholder ?? displayValue(currentValue)}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  return (
    <input
      style={input}
      type="text"
      placeholder={placeholder ?? displayValue(currentValue)}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

function relativeTime(iso: string | null): string {
  if (!iso) return "nunca leído";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `hace ${Math.round(seconds)}s`;
  if (seconds < 3600) return `hace ${Math.round(seconds / 60)}m`;
  return `hace ${Math.round(seconds / 3600)}h`;
}

function SectionEditor({
  section,
  snapshot,
  edits,
  onEditField,
  onRefresh,
}: {
  section: ConfigSectionSchema;
  snapshot: SectionSnapshot | undefined;
  edits: Record<string, string>;
  onEditField: (field: string, raw: string) => void;
  onRefresh: () => void;
}) {
  const current = snapshot?.values ?? {};
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
        <h3 style={{ margin: 0 }}>{section.display_name}</h3>
        <span style={{ ...RISK_STYLE[section.risk], borderRadius: 12, padding: "0.05rem 0.6rem", fontSize: "0.75rem" }}>
          {section.risk}
        </span>
        <span style={{ ...styles.dim, fontSize: "0.85rem" }}>{section.description}</span>
        <span style={{ marginLeft: "auto", ...styles.dim, fontSize: "0.8rem" }}>
          Leído {relativeTime(snapshot?.last_read_at ?? null)}
        </span>
        <button style={btn} onClick={onRefresh}>Refrescar</button>
      </div>
      {snapshot && Object.keys(current).length === 0 && (
        <p style={styles.dim}>
          Aún no se ha leído esta sección. Pulsa <em>Refrescar</em> para encolar un GET.
        </p>
      )}
      <table style={styles.table}>
        <thead>
          <tr>
            <th style={styles.th}>Campo</th>
            <th style={styles.th}>Tipo</th>
            <th style={styles.th}>Valor actual</th>
            <th style={styles.th}>Nuevo valor</th>
          </tr>
        </thead>
        <tbody>
          {section.fields.map((f) => {
            const current_value = readCurrentValue(current, f.name);
            return (
              <tr key={f.name}>
                <td style={{ ...styles.td, ...styles.mono }}>{f.name}</td>
                <td style={{ ...styles.td, ...styles.dim }}>
                  {f.kind}
                  {f.kind === "enum" && f.enum_values.length > 0 ? "" : ""}
                </td>
                <td style={{ ...styles.td, ...styles.mono }}>{displayValue(current_value)}</td>
                <td style={styles.td}>
                  <FieldControl
                    field={f}
                    currentValue={current_value}
                    editedRaw={edits[f.name]}
                    onChange={(raw) => onEditField(f.name, raw)}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

interface ChangeItem {
  section: string;
  field: string;
  from: unknown;
  to: unknown;
}

/** Extrae únicamente los campos con valor distinto del actual. */
function collectChanges(
  schema: ConfigSchemaOut,
  edits: Record<string, Record<string, string>>,
  snapshots: Record<string, SectionSnapshot>,
): { payload: Record<string, Record<string, unknown>>; changes: ChangeItem[] } {
  const payload: Record<string, Record<string, unknown>> = {};
  const changes: ChangeItem[] = [];
  for (const section of schema.sections) {
    const sectionEdits = edits[section.name] ?? {};
    const current = snapshots[section.name]?.values ?? {};
    const values: Record<string, unknown> = {};
    for (const field of section.fields) {
      if (!field.editable) continue;
      const raw = sectionEdits[field.name];
      if (raw === undefined) continue;
      const editedValue = normalizeInputForCompare(field, raw);
      if (editedValue === null) continue; // "— sin cambio —"
      const cur = readCurrentValue(current, field.name);
      if (equalValues(cur, editedValue)) continue;
      values[field.name] = editedValue;
      changes.push({ section: section.name, field: field.name, from: cur, to: editedValue });
    }
    if (Object.keys(values).length > 0) payload[section.name] = values;
  }
  return { payload, changes };
}

export function ConfigEditor({ summaries }: Props) {
  const queryClient = useQueryClient();
  const [nodeId, setNodeId] = useState("");
  const [activeGroup, setActiveGroup] = useState<string>("General");
  const [activeSection, setActiveSection] = useState<string>("owner");
  const [edits, setEdits] = useState<Record<string, Record<string, string>>>({});
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");

  const schema = useQuery({ queryKey: ["config-schema"], queryFn: fetchConfigSchema, staleTime: 60 * 60_000 });
  const nodeConfig = useQuery({
    queryKey: ["node-config", nodeId],
    queryFn: () => fetchNodeConfig(nodeId),
    enabled: nodeId !== "",
    refetchInterval: 10_000,
  });
  const operations = useQuery({
    queryKey: ["operations", "config-editor"],
    queryFn: () => fetchOperations(undefined, 20),
    refetchInterval: 5_000,
    enabled: nodeId !== "",
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["node-config", nodeId] });
    queryClient.invalidateQueries({ queryKey: ["operations"] });
  };
  const refresh = useMutation({
    mutationFn: (sections: string[] | undefined) => refreshNodeConfig(nodeId, sections),
    onSettled: invalidate,
  });
  const apply = useMutation({
    mutationFn: (payload: Record<string, Record<string, unknown>>) => applyNodeConfig(nodeId, payload),
    onSettled: () => {
      invalidate();
      setEdits({});
      setConfirmOpen(false);
      setConfirmText("");
    },
  });

  const snapshotsBySection = useMemo(() => {
    const m: Record<string, SectionSnapshot> = {};
    for (const s of nodeConfig.data?.sections ?? []) m[s.section] = s;
    return m;
  }, [nodeConfig.data]);

  const sectionsByName = useMemo(() => {
    const m: Record<string, ConfigSectionSchema> = {};
    for (const s of schema.data?.sections ?? []) m[s.name] = s;
    return m;
  }, [schema.data]);

  const currentSection = sectionsByName[activeSection];
  const editsForSection = edits[activeSection] ?? {};

  useEffect(() => {
    // Al cambiar de nodo, empezamos siempre en la pestaña "General"
    setActiveGroup("General");
    setActiveSection("owner");
    setEdits({});
    setConfirmOpen(false);
  }, [nodeId]);

  const { payload, changes } = useMemo(
    () => (schema.data ? collectChanges(schema.data, edits, snapshotsBySection) : { payload: {}, changes: [] }),
    [schema.data, edits, snapshotsBySection],
  );

  // Riesgo agregado del payload: el más alto de las secciones tocadas
  const aggregatedRisk = useMemo(() => {
    let level = 0;
    const order: Record<string, number> = { SAFE: 0, WARNING: 1, DANGEROUS: 2 };
    for (const name of Object.keys(payload)) {
      const s = sectionsByName[name];
      if (s) level = Math.max(level, order[s.risk] ?? 0);
    }
    return (["SAFE", "WARNING", "DANGEROUS"][level] ?? "SAFE") as "SAFE" | "WARNING" | "DANGEROUS";
  }, [payload, sectionsByName]);

  if (schema.isLoading) return <div style={styles.card}>Cargando esquema…</div>;
  if (!schema.data) return <div style={styles.card}>No se pudo cargar el esquema.</div>;

  return (
    <div>
      {/* Selector de nodo + refresco global */}
      <div style={styles.card}>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
          <h2 style={{ margin: 0 }}>Editor de configuración</h2>
          <NodeSelect value={nodeId} onChange={setNodeId} options={summaries} showOnlineStatus />
          <button
            style={{ ...btn, opacity: nodeId ? 1 : 0.5 }}
            disabled={!nodeId || refresh.isPending}
            onClick={() => refresh.mutate(undefined)}
          >
            Refrescar todo
          </button>
          {refresh.isSuccess && (
            <span style={styles.dim}>
              Encoladas {refresh.data.operation_ids.length} lecturas. Se irán completando por la cola.
            </span>
          )}
          {refresh.isError && <span style={styles.bad}>{String(refresh.error)}</span>}
        </div>
        <p style={{ ...styles.dim, fontSize: "0.85rem", marginBottom: 0 }}>
          Modifica varios parámetros en distintas secciones y pulsa <em>Aplicar cambios</em>. El
          sistema encolará los SETs necesarios en el orden correcto y verificará cada sección con
          una lectura posterior.
        </p>
      </div>

      {!nodeId && <div style={styles.card}><p style={styles.dim}>Selecciona un nodo para empezar.</p></div>}

      {nodeId && (
        <div style={styles.card}>
          {/* Pestañas de grupos */}
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.5rem" }}>
            {Object.keys(schema.data.ui_groups).map((group) => (
              <button
                key={group}
                style={{
                  ...btn,
                  background: activeGroup === group ? "var(--accent)" : "transparent",
                }}
                onClick={() => {
                  setActiveGroup(group);
                  const first = schema.data!.ui_groups[group][0];
                  if (first) setActiveSection(first);
                }}
              >
                {group}
              </button>
            ))}
          </div>
          {/* Secciones dentro del grupo */}
          <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap", marginBottom: "0.8rem" }}>
            {(schema.data.ui_groups[activeGroup] ?? []).map((sectionName) => {
              const s = sectionsByName[sectionName];
              if (!s) return null;
              const hasEdits = Object.keys(edits[sectionName] ?? {}).length > 0;
              return (
                <button
                  key={sectionName}
                  style={{
                    ...btn,
                    background: activeSection === sectionName ? "var(--border)" : "transparent",
                    borderColor: hasEdits ? "var(--warn)" : "var(--border)",
                    fontSize: "0.8rem",
                  }}
                  onClick={() => setActiveSection(sectionName)}
                  title={s.description}
                >
                  {s.display_name}
                  {hasEdits ? " •" : ""}
                </button>
              );
            })}
          </div>

          {currentSection && (
            <SectionEditor
              section={currentSection}
              snapshot={snapshotsBySection[currentSection.name]}
              edits={editsForSection}
              onEditField={(f, raw) =>
                setEdits((prev) => {
                  const sec = { ...(prev[activeSection] ?? {}) };
                  if (raw === "") delete sec[f];
                  else sec[f] = raw;
                  return { ...prev, [activeSection]: sec };
                })
              }
              onRefresh={() => refresh.mutate([activeSection])}
            />
          )}
        </div>
      )}

      {/* Resumen y aplicación */}
      {nodeId && (
        <div style={styles.card}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap" }}>
            <h3 style={{ margin: 0 }}>
              Cambios pendientes ({changes.length})
              {changes.length > 0 && (
                <span
                  style={{
                    ...RISK_STYLE[aggregatedRisk],
                    borderRadius: 12,
                    padding: "0.05rem 0.6rem",
                    fontSize: "0.75rem",
                    marginLeft: 8,
                  }}
                >
                  {aggregatedRisk}
                </span>
              )}
            </h3>
            <span>
              <button style={btn} disabled={changes.length === 0} onClick={() => setEdits({})}>
                Descartar
              </button>{" "}
              <button
                style={{ ...btn, background: changes.length ? "var(--accent)" : "transparent" }}
                disabled={changes.length === 0 || apply.isPending}
                onClick={() => setConfirmOpen(true)}
              >
                Aplicar cambios…
              </button>
            </span>
          </div>
          {changes.length === 0 ? (
            <p style={styles.dim}>Modifica algún campo para ver aquí el resumen.</p>
          ) : (
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>Sección</th>
                  <th style={styles.th}>Campo</th>
                  <th style={styles.th}>De</th>
                  <th style={styles.th}>A</th>
                </tr>
              </thead>
              <tbody>
                {changes.map((c) => (
                  <tr key={`${c.section}.${c.field}`}>
                    <td style={{ ...styles.td, ...styles.mono }}>{c.section}</td>
                    <td style={{ ...styles.td, ...styles.mono }}>{c.field}</td>
                    <td style={{ ...styles.td, ...styles.mono }}>{displayValue(c.from)}</td>
                    <td style={{ ...styles.td, ...styles.mono }}>{displayValue(c.to)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {confirmOpen && (
            <div style={{ border: "1px solid var(--warn)", borderRadius: 8, padding: "0.8rem", marginTop: "0.8rem" }}>
              <p style={{ marginTop: 0 }}>
                Vas a aplicar <strong>{changes.length}</strong> cambio{changes.length === 1 ? "" : "s"} sobre{" "}
                <strong>{nodeId}</strong>. Se encolará una operación por sección modificada, cada una
                con verificación por lectura posterior. Nivel de riesgo agregado:{" "}
                <span style={{ ...RISK_STYLE[aggregatedRisk], padding: "0 0.4rem", borderRadius: 6 }}>
                  {aggregatedRisk}
                </span>
              </p>
              <p style={styles.dim}>Teclea el node_id (<span style={styles.mono}>{nodeId}</span>) para confirmar:</p>
              <input style={input} value={confirmText} onChange={(e) => setConfirmText(e.target.value)} />
              <button
                style={{ ...btn, marginLeft: 8 }}
                disabled={confirmText !== nodeId || apply.isPending}
                onClick={() => apply.mutate(payload)}
              >
                Confirmar y añadir a la cola
              </button>
              <button style={{ ...btn, marginLeft: 8 }} onClick={() => { setConfirmOpen(false); setConfirmText(""); }}>
                Cancelar
              </button>
              {apply.isError && <p style={styles.bad}>{String(apply.error)}</p>}
            </div>
          )}
        </div>
      )}

      {/* Estado del pipeline: últimas operaciones relacionadas */}
      {nodeId && operations.data && (
        <div style={styles.card}>
          <h3 style={{ margin: 0 }}>Operaciones recientes</h3>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>#</th>
                <th style={styles.th}>Tipo</th>
                <th style={styles.th}>Sección</th>
                <th style={styles.th}>Estado</th>
                <th style={styles.th}>Intentos</th>
              </tr>
            </thead>
            <tbody>
              {operations.data
                .filter((o) => o.target_node_id === nodeId)
                .slice(0, 8)
                .map((o) => (
                  <tr key={o.id}>
                    <td style={styles.td}>{o.id}</td>
                    <td style={{ ...styles.td, ...styles.mono }}>{o.operation_type}</td>
                    <td style={{ ...styles.td, ...styles.mono }}>{String(o.params.section ?? "—")}</td>
                    <td style={styles.td}>{o.status}</td>
                    <td style={styles.td}>{o.attempts}/{o.max_attempts}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

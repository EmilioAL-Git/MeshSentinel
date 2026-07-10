import { useMemo, useState, type CSSProperties } from "react";
import {
  CATEGORY_LABEL,
  type ActivityCategory,
  type ActivityEntry,
  type ActivitySeverity,
} from "../activity";
import { type GatewayOut, type NodeSummaryOut } from "../api/client";
import { NodeSelect } from "./NodeSelect";
import { styles } from "../styles";
import { chipStyle } from "../tokens";

const input: CSSProperties = {
  background: "var(--bg)",
  border: "1px solid var(--border)",
  color: "var(--text)",
  borderRadius: 6,
  padding: "0.3rem 0.5rem",
};
const btn: CSSProperties = { ...input, cursor: "pointer" };

const SEVERITY_COLOR: Record<ActivitySeverity, string> = {
  info: "var(--text-dim)",
  ok: "var(--ok)",
  warn: "var(--warn)",
  error: "var(--crit)",
};

const CATEGORY_COLOR: Record<ActivityCategory, string> = {
  operacion: "var(--accent)",
  batch: "var(--accent)",
  pasarela: "var(--ok)",
  alerta: "var(--crit)",
  malla: "var(--text-faint)",
};

const ALL_CATEGORIES = Object.keys(CATEGORY_LABEL) as ActivityCategory[];

export function ActivityConsole({
  entries,
  summaries,
  gateways,
  onClear,
}: {
  entries: ActivityEntry[];
  summaries: NodeSummaryOut[];
  gateways: GatewayOut[];
  onClear: () => void;
}) {
  const [nodeFilter, setNodeFilter] = useState("");
  const [batchFilter, setBatchFilter] = useState("");
  const [gatewayFilter, setGatewayFilter] = useState("");
  const [categories, setCategories] = useState<Set<ActivityCategory>>(new Set(ALL_CATEGORIES));

  // Batches vistos en el buffer (para el filtro)
  const batchIds = useMemo(
    () =>
      [...new Set(entries.map((e) => e.batchId).filter((b): b is number => b != null))].sort(
        (a, b) => b - a,
      ),
    [entries],
  );
  const gatewayIds = useMemo(() => {
    const ids = new Set(gateways.map((g) => g.gateway_id));
    // "system": origen de eventos internos del backend (alertas, actividad),
    // no una pasarela real — debe coincidir con SYSTEM_SOURCE en envelopes.py
    for (const e of entries) if (e.gatewayId && e.gatewayId !== "system") ids.add(e.gatewayId);
    return [...ids].sort();
  }, [entries, gateways]);

  const filtered = useMemo(
    () =>
      entries.filter(
        (e) =>
          categories.has(e.category) &&
          (nodeFilter === "" || e.nodeId === nodeFilter) &&
          (batchFilter === "" || e.batchId === Number(batchFilter)) &&
          (gatewayFilter === "" || e.gatewayId === gatewayFilter),
      ),
    [entries, categories, nodeFilter, batchFilter, gatewayFilter],
  );

  const toggleCategory = (c: ActivityCategory) => {
    const next = new Set(categories);
    if (next.has(c)) next.delete(c);
    else next.add(c);
    setCategories(next);
  };

  const hasFilters =
    nodeFilter !== "" || batchFilter !== "" || gatewayFilter !== "" || categories.size !== ALL_CATEGORIES.length;

  return (
    <div style={styles.card}>
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
        <h2 style={{ margin: 0 }}>Actividad del sistema</h2>
        <span style={{ ...styles.ok, fontSize: "0.8rem" }}>● en vivo</span>
        <span style={{ marginLeft: "auto", ...styles.dim, fontSize: "0.85rem" }}>
          {filtered.length}
          {hasFilters ? ` de ${entries.length}` : ""} eventos
        </span>
        <button style={btn} onClick={onClear} disabled={entries.length === 0}>
          Limpiar vista
        </button>
      </div>

      {/* Filtros */}
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap", margin: "0.8rem 0" }}>
        <NodeSelect value={nodeFilter} onChange={setNodeFilter} options={summaries} placeholder="— todos los nodos —" />
        <select style={input} value={batchFilter} onChange={(e) => setBatchFilter(e.target.value)}>
          <option value="">— todos los batches —</option>
          {batchIds.map((b) => (
            <option key={b} value={b}>
              Batch #{b}
            </option>
          ))}
        </select>
        <select style={input} value={gatewayFilter} onChange={(e) => setGatewayFilter(e.target.value)}>
          <option value="">— todas las pasarelas —</option>
          {gatewayIds.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
        </select>
        <span style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap" }}>
          {ALL_CATEGORIES.map((c) => (
            <button
              key={c}
              style={{
                ...btn,
                fontSize: "0.8rem",
                padding: "0.15rem 0.6rem",
                borderRadius: 12,
                background: categories.has(c) ? CATEGORY_COLOR[c] : "transparent",
                borderColor: CATEGORY_COLOR[c],
                opacity: categories.has(c) ? 1 : 0.5,
              }}
              onClick={() => toggleCategory(c)}
              title={`Mostrar/ocultar eventos de tipo ${CATEGORY_LABEL[c]}`}
            >
              {CATEGORY_LABEL[c]}
            </button>
          ))}
        </span>
      </div>

      {/* Lista de eventos (más recientes arriba) */}
      {filtered.length === 0 ? (
        <p style={styles.dim}>
          {entries.length === 0
            ? "Esperando eventos… La consola muestra en tiempo real la actividad del sistema."
            : "Ningún evento coincide con los filtros actuales."}
        </p>
      ) : (
        <div style={{ maxHeight: "70vh", overflowY: "auto" }}>
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {filtered.map((e) => (
              <li
                key={e.id}
                style={{
                  display: "flex",
                  gap: "0.6rem",
                  alignItems: "baseline",
                  padding: "0.25rem 0",
                  borderBottom: "1px solid var(--border-subtle)",
                }}
              >
                <span style={{ ...styles.mono, ...styles.dim, whiteSpace: "nowrap" }}>{e.time}</span>
                <span
                  style={{
                    ...chipStyle(CATEGORY_COLOR[e.category]),
                    padding: "0 0.5rem",
                    fontSize: "0.7rem",
                  }}
                >
                  {CATEGORY_LABEL[e.category]}
                </span>
                {e.gatewayId && e.gatewayId !== "system" && (
                  <span
                    title={`Pasarela de origen: ${e.gatewayId}`}
                    style={{
                      ...styles.mono,
                      border: "1px solid var(--border)",
                      borderRadius: 12,
                      padding: "0 0.4rem",
                      fontSize: "0.7rem",
                      whiteSpace: "nowrap",
                      color: "var(--text-dim)",
                    }}
                  >
                    {e.gatewayId}
                  </span>
                )}
                <span style={{ color: SEVERITY_COLOR[e.severity], fontSize: "0.9rem" }}>{e.text}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p style={{ ...styles.dim, fontSize: "0.8rem", marginBottom: 0 }}>
        Monitor de actividad para el operador: operaciones remotas (cola → envío → respuesta →
        verificación), batches, pasarelas (USB), alertas y tráfico de la malla. Se conservan los
        últimos 500 eventos de la sesión.
      </p>
    </div>
  );
}

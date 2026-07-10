import { useMemo, useState } from "react";
import {
  CATEGORY_LABEL,
  type ActivityCategory,
  type ActivityEntry,
  type ActivitySeverity,
} from "../activity";
import { type GatewayOut, type NodeSummaryOut } from "../api/client";
import { NodeSelect } from "./NodeSelect";

/**
 * Registro (identidad v0.8): la actividad del sistema como terminal de
 * eventos a sangre completa — mono, timestamp, gutter de severidad —
 * en vez de una tarjeta con lista. Mismos filtros y buffer de 500.
 */

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
    <div className="ws">
      <div className="toolbar">
        <span className="microlabel">Registro de eventos</span>
        <span className="noc-pulse" style={{ color: "var(--ok)", fontSize: 9 }}>●</span>
        <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>
          {filtered.length}
          {hasFilters ? `/${entries.length}` : ""} eventos · buffer 500
        </span>
        <span className="sep" />
        <NodeSelect value={nodeFilter} onChange={setNodeFilter} options={summaries} placeholder="— todos los nodos —" />
        <select className="input" value={batchFilter} onChange={(e) => setBatchFilter(e.target.value)}>
          <option value="">— todos los lotes —</option>
          {batchIds.map((b) => (
            <option key={b} value={b}>
              Lote #{b}
            </option>
          ))}
        </select>
        <select className="input" value={gatewayFilter} onChange={(e) => setGatewayFilter(e.target.value)}>
          <option value="">— todas las pasarelas —</option>
          {gatewayIds.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
        </select>
        <span className="seg">
          {ALL_CATEGORIES.map((c) => (
            <button
              key={c}
              className={categories.has(c) ? "on" : undefined}
              style={categories.has(c) ? { color: CATEGORY_COLOR[c], background: `color-mix(in srgb, ${CATEGORY_COLOR[c]} 12%, transparent)` } : undefined}
              onClick={() => toggleCategory(c)}
              title={`Mostrar/ocultar eventos de tipo ${CATEGORY_LABEL[c]}`}
            >
              {CATEGORY_LABEL[c]}
            </button>
          ))}
        </span>
        <span style={{ marginLeft: "auto" }} />
        <button className="btn ghost" onClick={onClear} disabled={entries.length === 0}>
          Limpiar
        </button>
      </div>

      {/* Terminal de eventos (más recientes arriba) */}
      <div className="ws-scroll">
        {filtered.length === 0 ? (
          <div className="empty">
            {entries.length === 0
              ? "Esperando eventos… El registro muestra en tiempo real la actividad del sistema: operaciones remotas (cola → envío → respuesta → verificación), lotes, pasarelas, alertas y tráfico de la malla."
              : "Ningún evento coincide con los filtros actuales."}
          </div>
        ) : (
          <div className="termlog" style={{ padding: "0.3rem 0" }}>
            {filtered.map((e) => (
              <div key={e.id} className="line" style={{ borderLeftColor: CATEGORY_COLOR[e.category] }}>
                <span className="ts">{e.time}</span>
                <span className="src" style={{ color: CATEGORY_COLOR[e.category] }}>
                  {CATEGORY_LABEL[e.category].toLowerCase()}
                </span>
                {e.gatewayId && e.gatewayId !== "system" && (
                  <span className="src" title={`Pasarela de origen: ${e.gatewayId}`}>{e.gatewayId}</span>
                )}
                <span className="msg" style={{ color: SEVERITY_COLOR[e.severity] }}>
                  {e.text}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

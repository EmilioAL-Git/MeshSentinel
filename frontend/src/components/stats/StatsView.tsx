import { useQuery } from "@tanstack/react-query";
import { displayName, fetchStatsSummary, type StatRecordOut } from "../../api/client";

/**
 * Estadísticas (identidad v0.8): panel de datos curiosos sobre la malla —
 * récords individuales por nodo (más air TX, más caliente, más uptime...),
 * calculados en `StatsService` (backend) sobre los mismos datos ya
 * persistidos. Sin relación con el Dashboard/Situación (nada de salud ni
 * umbrales); un solo endpoint self-contained, mismo patrón que Enlaces.
 */

function formatValue(r: StatRecordOut): string {
  if (r.unit === "s") {
    const totalMin = Math.round(r.value / 60);
    const days = Math.floor(totalMin / 1440);
    const hours = Math.floor((totalMin % 1440) / 60);
    const mins = totalMin % 60;
    if (days > 0) return `${days} d ${hours} h`;
    if (hours > 0) return `${hours} h ${mins} min`;
    return `${mins} min`;
  }
  if (r.unit === "min") {
    if (r.value < 60) return `hace ${Math.round(r.value)} min`;
    const hours = r.value / 60;
    if (hours < 48) return `hace ${Math.round(hours)} h`;
    return `hace ${Math.round(hours / 24)} d`;
  }
  const v = Number.isInteger(r.value) ? String(r.value) : r.value.toFixed(1);
  return r.unit ? `${v} ${r.unit}` : v;
}

function RecordCard({ r, onOpenNode }: { r: StatRecordOut; onOpenNode: (nodeId: string) => void }) {
  return (
    <div className="panel" style={{ minHeight: 112 }}>
      <div className="panel-head">
        <span className="panel-title">{r.label}</span>
      </div>
      <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ fontSize: 22, lineHeight: 1 }} aria-hidden="true">{r.icon}</div>
        <div
          className="mono"
          style={{ fontSize: 18, fontVariantNumeric: "tabular-nums", color: "var(--text)" }}
        >
          {formatValue(r)}
        </div>
        <button
          className="btn"
          style={{ alignSelf: "flex-start", fontSize: 11, padding: "0.15rem 0.5rem" }}
          onClick={() => onOpenNode(r.node_id)}
        >
          {displayName({ node_id: r.node_id, short_name: r.short_name, long_name: r.long_name })}
        </button>
      </div>
    </div>
  );
}

export function StatsView({ onOpenNode }: { onOpenNode: (nodeId: string) => void }) {
  const stats = useQuery({
    queryKey: ["stats", "summary"],
    queryFn: fetchStatsSummary,
    refetchInterval: 20_000,
  });

  const s = stats.data;
  const records = s?.records ?? [];

  return (
    <div className="ws">
      <div className="toolbar">
        <span className="microlabel">Datos curiosos de la malla</span>
      </div>

      <div className="kpis">
        <div className="kpi">
          <div className="v">{s?.nodes_total ?? "—"}</div>
          <div className="k">Nodos</div>
        </div>
        <div className="kpi">
          <div className="v" style={{ color: "var(--ok)" }}>{s?.nodes_online ?? "—"}</div>
          <div className="k">En línea</div>
        </div>
        <div className="kpi">
          <div className="v">{s?.network_age_days ?? "—"}</div>
          <div className="k">Días de malla</div>
        </div>
        <div className="kpi">
          <div className="v">{s?.events_last_24h ?? "—"}</div>
          <div className="k">Eventos 24 h</div>
        </div>
      </div>

      <div className="ws-scroll" style={{ padding: "0.75rem" }}>
        {stats.isLoading && <div className="empty">Cargando…</div>}
        {!stats.isLoading && records.length === 0 && (
          <div className="empty">Sin datos suficientes todavía para calcular récords.</div>
        )}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))",
            gap: "0.75rem",
          }}
        >
          {records.map((r) => (
            <RecordCard key={r.key} r={r} onOpenNode={onOpenNode} />
          ))}
        </div>
      </div>
    </div>
  );
}

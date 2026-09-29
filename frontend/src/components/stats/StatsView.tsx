import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { displayName, fetchStatsRanking, fetchStatsSummary, type StatRecordOut } from "../../api/client";
import { Modal } from "../shell/Modal";
import { fmtDuration } from "../../time";

/**
 * Estadísticas (identidad v0.8): panel de datos curiosos sobre la malla —
 * récords individuales por nodo (más air TX, más caliente, más uptime...),
 * calculados en `StatsService` (backend) sobre los mismos datos ya
 * persistidos. Sin relación con el Dashboard/Situación (nada de salud ni
 * umbrales); un solo endpoint self-contained, mismo patrón que Enlaces.
 * Cada tarjeta es solo la cabeza de un ranking completo: al pulsarla se
 * despliega la lista entera de nodos por debajo del top (`GET
 * /stats/ranking/{key}`), mejor primero.
 */

function formatValue(r: StatRecordOut): string {
  if (r.unit === "s") return fmtDuration(r.value);
  if (r.unit === "min") return `hace ${fmtDuration(r.value * 60)}`;
  const v = Number.isInteger(r.value) ? String(r.value) : r.value.toFixed(1);
  return r.unit ? `${v} ${r.unit}` : v;
}

function RecordCard({ r, onOpen }: { r: StatRecordOut; onOpen: (r: StatRecordOut) => void }) {
  return (
    <div
      className="panel"
      style={{ minHeight: 112, cursor: "pointer" }}
      onClick={() => onOpen(r)}
      title="Ver el ranking completo"
    >
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
        <div className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>
          {displayName({ node_id: r.node_id, short_name: r.short_name, long_name: r.long_name })}
        </div>
      </div>
    </div>
  );
}

function RankingModal({
  record,
  onClose,
  onOpenNode,
}: {
  record: StatRecordOut;
  onClose: () => void;
  onOpenNode: (nodeId: string) => void;
}) {
  const ranking = useQuery({
    queryKey: ["stats", "ranking", record.key],
    queryFn: () => fetchStatsRanking(record.key),
  });
  const rows = ranking.data ?? [];

  return (
    <Modal title={`${record.icon} ${record.label}`} onClose={onClose}>
      {ranking.isLoading && <div className="empty">Cargando…</div>}
      {!ranking.isLoading && rows.length === 0 && <div className="empty">Sin nodos con este dato.</div>}
      <div style={{ display: "flex", flexDirection: "column" }}>
        {rows.map((row, i) => (
          <button
            key={row.node_id}
            className="btn"
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.6rem",
              justifyContent: "flex-start",
              border: "none",
              borderBottom: "1px solid var(--border-subtle)",
              borderRadius: 0,
              background: i === 0 ? "var(--accent-tint)" : "transparent",
              padding: "0.4rem 0.3rem",
            }}
            onClick={() => {
              onOpenNode(row.node_id);
              onClose();
            }}
          >
            <span className="mono" style={{ fontSize: 11, color: "var(--text-faint)", width: 28, flexShrink: 0 }}>
              #{i + 1}
            </span>
            <span style={{ flex: 1, minWidth: 0, textAlign: "left", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {displayName({ node_id: row.node_id, short_name: row.short_name, long_name: row.long_name })}
            </span>
            <span className="mono" style={{ fontSize: 12.5, fontVariantNumeric: "tabular-nums", flexShrink: 0 }}>
              {formatValue(row)}
            </span>
          </button>
        ))}
      </div>
    </Modal>
  );
}

export function StatsView({ onOpenNode }: { onOpenNode: (nodeId: string) => void }) {
  const stats = useQuery({
    queryKey: ["stats", "summary"],
    queryFn: fetchStatsSummary,
    refetchInterval: 20_000,
  });
  const [openRecord, setOpenRecord] = useState<StatRecordOut | null>(null);

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
            <RecordCard key={r.key} r={r} onOpen={setOpenRecord} />
          ))}
        </div>
      </div>

      {openRecord && (
        <RankingModal record={openRecord} onClose={() => setOpenRecord(null)} onOpenNode={onOpenNode} />
      )}
    </div>
  );
}

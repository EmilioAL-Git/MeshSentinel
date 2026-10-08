import { useVirtualizer } from "@tanstack/react-virtual";
import { downloadText, stamp, toCsv } from "../../utils/exportData";
import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useUrlNumber } from "../../hooks/useUrlState";
import { displayName, fetchStatsRanking, fetchStatsSummary, type StatRecordOut } from "../../api/client";
import { Modal } from "../shell/Modal";
import { fmtDuration } from "../../time";
import { useActiveGroup } from "../../context/GroupContext";

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

const MAX_HOURS = 168; // 1 semana
const PRESETS = [
  { h: 1, label: "1 h" },
  { h: 6, label: "6 h" },
  { h: 24, label: "24 h" },
  { h: 72, label: "3 d" },
  { h: 168, label: "7 d" },
];

function clampHours(h: number): number {
  return Math.max(1, Math.min(MAX_HOURS, Math.round(h) || 1));
}

function windowLabel(h: number): string {
  const d = Math.floor(h / 24);
  const r = h % 24;
  return [d ? `${d} d` : "", r ? `${r} h` : ""].filter(Boolean).join(" ") || "1 h";
}

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

const ROW_HEIGHT = 34;

function RankingModal({
  record,
  hours,
  onClose,
  onOpenNode,
}: {
  record: StatRecordOut;
  hours: number;
  onClose: () => void;
  onOpenNode: (nodeId: string) => void;
}) {
  const { activeGroupId } = useActiveGroup();
  const ranking = useQuery({
    queryKey: ["stats", "ranking", record.key, hours, activeGroupId],
    queryFn: () => fetchStatsRanking(record.key, hours, activeGroupId),
  });
  const rows = ranking.data ?? [];
  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  });

  return (
    <Modal title={`${record.icon} ${record.label} · ${windowLabel(hours)}`} onClose={onClose}>
      {ranking.isLoading && <div className="empty">Cargando…</div>}
      {!ranking.isLoading && rows.length === 0 && <div className="empty">Sin nodos con este dato.</div>}
      {rows.length > 0 && (
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 6 }}>
          <button
            className="btn ghost"
            title={`Guarda en un CSV (Excel) el ranking completo: ${rows.length} nodos`}
            onClick={() =>
              downloadText(
                `ranking-${record.key}-${stamp()}.csv`,
                "text/csv",
                toCsv(
                  ["posicion", "node_id", "short_name", "long_name", "valor"],
                  rows.map((r, i) => [i + 1, r.node_id, r.short_name, r.long_name, formatValue(r)]),
                ),
                true,
              )
            }
          >
            ⤓ CSV
          </button>
        </div>
      )}
      {/* Virtualizado: el ranking completo puede ser de ~1000 nodos */}
      <div ref={scrollRef} style={{ maxHeight: "60vh", overflowY: "auto" }}>
        <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
          {virtualizer.getVirtualItems().map((v) => {
            const row = rows[v.index];
            const i = v.index;
            return (
              <button
                key={row.node_id}
                className="btn"
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  height: ROW_HEIGHT,
                  transform: `translateY(${v.start}px)`,
                  display: "flex",
                  alignItems: "center",
                  gap: "0.6rem",
                  justifyContent: "flex-start",
                  border: "none",
                  borderBottom: "1px solid var(--border-subtle)",
                  borderRadius: 0,
                  background: i === 0 ? "var(--accent-tint)" : "transparent",
                  padding: "0 0.3rem",
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
            );
          })}
        </div>
      </div>
    </Modal>
  );
}

export function StatsView({ onOpenNode }: { onOpenNode: (nodeId: string) => void }) {
  const [hoursParam, setHours] = useUrlNumber("stats.h", 168);
  const hours = clampHours(hoursParam ?? 168);
  const days = Math.floor(hours / 24);
  const restHours = hours % 24;
  const { activeGroupId, activeGroup } = useActiveGroup();
  const stats = useQuery({
    queryKey: ["stats", "summary", hours, activeGroupId],
    queryFn: () => fetchStatsSummary(hours, activeGroupId),
    refetchInterval: 20_000,
  });
  const [openRecord, setOpenRecord] = useState<StatRecordOut | null>(null);

  const s = stats.data;
  const records = s?.records ?? [];

  return (
    <div className="ws">
      <div className="toolbar">
        <span className="microlabel">Datos curiosos de {activeGroup ? `${activeGroup.name}` : "la malla"} · últimos {windowLabel(hours)}</span>
        <span style={{ flex: 1 }} />
        <div className="seg">
          {PRESETS.map((p) => (
            <button key={p.h} className={hours === p.h ? "on" : ""} onClick={() => setHours(p.h)}>
              {p.label}
            </button>
          ))}
        </div>
        <label className="microlabel" style={{ display: "flex", alignItems: "center", gap: 4 }}>
          Días
          <input
            className="input mono"
            type="number"
            min={0}
            max={7}
            value={days}
            style={{ width: 52 }}
            onChange={(e) => setHours(clampHours(Number(e.target.value) * 24 + restHours))}
          />
        </label>
        <label className="microlabel" style={{ display: "flex", alignItems: "center", gap: 4 }}>
          Horas
          <input
            className="input mono"
            type="number"
            min={0}
            max={23}
            value={restHours}
            style={{ width: 52 }}
            onChange={(e) => setHours(clampHours(days * 24 + Math.max(0, Math.min(23, Number(e.target.value)))))}
          />
        </label>
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
          <div className="v">{s?.events_in_window ?? "—"}</div>
          <div className="k">Eventos {windowLabel(hours)}</div>
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
        <RankingModal record={openRecord} hours={hours} onClose={() => setOpenRecord(null)} onOpenNode={onOpenNode} />
      )}
    </div>
  );
}

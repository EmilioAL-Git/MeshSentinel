import { useQuery } from "@tanstack/react-query";
import type { CSSProperties, ReactNode } from "react";
import {
  fetchGatewayStats,
  type CriticalNodeOut,
  type CriticalReason,
  type DashboardSummaryOut,
  type NodeSummaryOut,
} from "../api/client";
import { styles } from "../styles";
import type { ActivityEntry } from "../activity";

interface Props {
  summary: DashboardSummaryOut | undefined;
  loading: boolean;
  activity: ActivityEntry[];
  favorites: NodeSummaryOut[];
  onNavigate: (view: "nodes" | "map" | "activity") => void;
  onShowDetail: (nodeId: string) => void;
}

const STATUS_STYLE: Record<string, CSSProperties> = {
  HEALTHY: { background: "#1f6f43", color: "#fff" },
  WARNING: { background: "#9e6a03", color: "#fff" },
  CRITICAL: { background: "#b62324", color: "#fff" },
};

const REASON_LABEL: Record<CriticalReason, string> = {
  low_battery: "Batería baja",
  inactive: "Sin actividad",
  degraded_snr: "SNR degradado",
};

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `hace ${Math.round(seconds)}s`;
  if (seconds < 3600) return `hace ${Math.round(seconds / 60)}m`;
  return `hace ${Math.round(seconds / 3600)}h`;
}

function fmtSeconds(s: number | null): string {
  if (s == null) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}

function Card({ label, value, accent }: { label: string; value: ReactNode; accent?: CSSProperties }) {
  return (
    <div style={{ ...styles.card, marginBottom: 0, minWidth: 150, flex: "1 1 150px" }}>
      <div style={{ ...styles.dim, fontSize: "0.8rem" }}>{label}</div>
      <div style={{ fontSize: "1.6rem", fontWeight: 600, ...accent }}>{value}</div>
    </div>
  );
}

function CriticalRow({ node, onShowDetail }: { node: CriticalNodeOut; onShowDetail: (id: string) => void }) {
  return (
    <tr>
      <td style={styles.td}>
        <strong>{node.short_name ?? "?"}</strong>{" "}
        <span style={styles.dim}>{node.long_name ?? ""}</span>
      </td>
      <td style={{ ...styles.td, ...styles.mono }}>{node.node_id}</td>
      <td style={styles.td}>
        {node.reasons.map((r) => (
          <span
            key={r}
            style={{ ...styles.badgeOffline, marginRight: 4, background: r === "low_battery" ? "#9e6a03" : "#6e2c31" }}
          >
            {REASON_LABEL[r]}
            {r === "low_battery" && node.battery_level != null ? ` (${node.battery_level}%)` : ""}
            {r === "degraded_snr" && node.snr != null ? ` (${node.snr} dB)` : ""}
          </span>
        ))}
      </td>
      <td style={styles.td}>{relativeTime(node.last_seen_at)}</td>
      <td style={styles.td}>
        <button
          onClick={() => onShowDetail(node.node_id)}
          style={{ background: "none", border: "1px solid #30363d", color: "#e6edf3", borderRadius: 6, cursor: "pointer", padding: "0.15rem 0.5rem" }}
        >
          Detalle →
        </button>
      </td>
    </tr>
  );
}

export function Dashboard({ summary, loading, activity, favorites, onNavigate, onShowDetail }: Props) {
  // Multi-Gateway (M6.2): solo interesa consultarlo/mostrarlo con ≥2 pasarelas
  const multiGateway = summary != null && summary.gateways_total >= 2;
  const gwStats = useQuery({
    queryKey: ["gateway-stats"],
    queryFn: fetchGatewayStats,
    refetchInterval: 30_000,
    enabled: multiGateway,
  });
  if (loading || !summary) {
    return <div style={styles.card}>Cargando resumen de la red…</div>;
  }
  const t = summary.thresholds;

  return (
    <div>
      {/* Estado general + accesos rápidos */}
      <div style={{ ...styles.card, display: "flex", alignItems: "center", gap: "1.5rem", flexWrap: "wrap" }}>
        <span
          style={{
            ...STATUS_STYLE[summary.status],
            borderRadius: 8,
            padding: "0.5rem 1.5rem",
            fontSize: "1.4rem",
            fontWeight: 700,
            letterSpacing: 1,
          }}
        >
          {summary.status}
        </span>
        <span style={styles.dim}>
          {summary.status === "HEALTHY" && "Red operativa: pasarelas conectadas y nodos dentro de los umbrales."}
          {summary.status === "WARNING" && "Atención: hay indicadores fuera de los umbrales configurados."}
          {summary.status === "CRITICAL" && "Intervención necesaria: revisa pasarelas y nodos críticos."}
        </span>
        <span style={{ marginLeft: "auto", display: "flex", gap: "0.5rem" }}>
          <button onClick={() => onNavigate("nodes")} style={quickBtn}>Nodos</button>
          <button onClick={() => onNavigate("map")} style={quickBtn}>Mapa</button>
          <button onClick={() => onNavigate("activity")} style={quickBtn}>Ver actividad</button>
        </span>
      </div>

      {/* Acceso rápido a favoritos (M1.2) */}
      {favorites.length > 0 && (
        <div style={{ ...styles.card, display: "flex", gap: "0.6rem", flexWrap: "wrap", alignItems: "center" }}>
          <span style={{ color: "#e3b341" }}>★ Favoritos:</span>
          {favorites.map((f) => (
            <button
              key={f.node.node_id}
              onClick={() => onShowDetail(f.node.node_id)}
              style={{
                background: "transparent",
                border: "1px solid #30363d",
                color: "#e6edf3",
                borderRadius: 12,
                padding: "0.15rem 0.7rem",
                cursor: "pointer",
                fontSize: "0.85rem",
              }}
            >
              <span style={f.node.online ? styles.ok : styles.bad}>●</span>{" "}
              {f.node.short_name ?? f.node.node_id}
            </button>
          ))}
        </div>
      )}

      {/* Tarjetas resumen */}
      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginBottom: "1rem" }}>
        <Card label="Nodos totales" value={summary.nodes_total} />
        <Card label="Online" value={summary.nodes_online} accent={styles.ok} />
        <Card
          label={`Offline (${summary.offline_percent}%)`}
          value={summary.nodes_offline}
          accent={summary.nodes_offline > 0 ? styles.bad : undefined}
        />
        <Card
          label="Pasarelas conectadas"
          value={`${summary.gateways_connected}/${summary.gateways_total}`}
          accent={summary.gateways_connected < summary.gateways_total ? styles.bad : styles.ok}
        />
        <Card
          label={`Batería < ${t.low_battery_percent}%`}
          value={summary.low_battery_count}
          accent={summary.low_battery_count > 0 ? { color: "#d29922" } : undefined}
        />
        <Card
          label="Batería media"
          value={summary.avg_battery_percent != null ? `${summary.avg_battery_percent}%` : "—"}
        />
        <Card label="Silencio medio" value={fmtSeconds(summary.avg_seconds_since_last_seen)} />
        <Card label="Eventos última hora" value={summary.events_last_hour} />
      </div>

      {/* Cobertura Multi-Gateway (M6.2): visible solo con ≥2 pasarelas */}
      {multiGateway && gwStats.data && (
        <div style={styles.card}>
          <div style={{ display: "flex", alignItems: "baseline", gap: "1rem", flexWrap: "wrap" }}>
            <h2 style={{ margin: 0 }}>Cobertura Multi-Gateway</h2>
            <span style={styles.dim}>
              {gwStats.data.nodes_observed} nodos observados · {gwStats.data.nodes_shared} con cobertura
              redundante ({gwStats.data.redundancy_percent}%)
            </span>
          </div>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Pasarela</th>
                <th style={styles.th}>Estado</th>
                <th style={styles.th}>Nodos visibles</th>
                <th style={styles.th}>Exclusivos</th>
                <th style={styles.th}>Compartidos</th>
                <th style={styles.th}>Primaria de</th>
                <th style={styles.th}>Última actividad</th>
              </tr>
            </thead>
            <tbody>
              {gwStats.data.gateways.map((g) => (
                <tr key={g.gateway_id}>
                  <td style={styles.td}>
                    <strong>{g.name ?? g.gateway_id}</strong>{" "}
                    <span style={{ ...styles.dim, ...styles.mono }}>{g.gateway_id}</span>
                  </td>
                  <td style={styles.td}>
                    <span style={g.status === "connected" ? styles.ok : styles.bad}>●</span> {g.status}
                  </td>
                  <td style={styles.td}>{g.nodes_visible}</td>
                  <td style={styles.td}>{g.nodes_exclusive}</td>
                  <td style={styles.td}>{g.nodes_shared}</td>
                  <td style={styles.td}>{g.primary_for}</td>
                  <td style={styles.td}>{relativeTime(g.last_heard_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div style={styles.layout}>
        {/* Nodos críticos */}
        <div style={styles.card}>
          <h2 style={{ marginTop: 0 }}>Nodos que requieren atención ({summary.critical_nodes.length})</h2>
          {summary.critical_nodes.length === 0 ? (
            <p style={styles.ok}>Ningún nodo requiere atención.</p>
          ) : (
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>Nodo</th>
                  <th style={styles.th}>ID</th>
                  <th style={styles.th}>Motivo</th>
                  <th style={styles.th}>Visto</th>
                  <th style={styles.th}></th>
                </tr>
              </thead>
              <tbody>
                {summary.critical_nodes.map((n) => (
                  <CriticalRow key={n.node_id} node={n} onShowDetail={onShowDetail} />
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Actividad reciente */}
        <div style={styles.card}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <h2 style={{ margin: 0 }}>Actividad reciente</h2>
            <button onClick={() => onNavigate("activity")} style={{ ...quickBtn, fontSize: "0.85rem" }}>
              Consola →
            </button>
          </div>
          {activity.length === 0 ? (
            <p style={styles.dim}>Esperando eventos…</p>
          ) : (
            <ul style={{ ...styles.mono, listStyle: "none", padding: 0, margin: 0 }}>
              {activity.map((a) => (
                <li key={a.id} style={{ padding: "0.2rem 0", borderBottom: "1px solid #21262d" }}>
                  <span style={styles.dim}>{a.time}</span> {a.text}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

const quickBtn: CSSProperties = {
  background: "transparent",
  color: "#e6edf3",
  border: "1px solid #30363d",
  borderRadius: 6,
  padding: "0.35rem 1rem",
  cursor: "pointer",
};

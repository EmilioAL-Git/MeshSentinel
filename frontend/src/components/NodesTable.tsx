import type { NodeSummaryOut } from "../api/client";
import { styles } from "../styles";

interface Props {
  summaries: NodeSummaryOut[];
  selected: string | null;
  onSelect: (nodeId: string) => void;
}

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `hace ${Math.round(seconds)}s`;
  if (seconds < 3600) return `hace ${Math.round(seconds / 60)}m`;
  return `hace ${Math.round(seconds / 3600)}h`;
}

export function NodesTable({ summaries, selected, onSelect }: Props) {
  return (
    <table style={styles.table}>
      <thead>
        <tr>
          <th style={styles.th}>Nodo</th>
          <th style={styles.th}>ID</th>
          <th style={styles.th}>Estado</th>
          <th style={styles.th}>Batería</th>
          <th style={styles.th}>SNR</th>
          <th style={styles.th}>Saltos</th>
          <th style={styles.th}>Posición</th>
          <th style={styles.th}>Visto</th>
        </tr>
      </thead>
      <tbody>
        {summaries.map(({ node, last_position, last_device_telemetry }) => (
          <tr
            key={node.node_id}
            style={{
              ...styles.rowHover,
              background: selected === node.node_id ? "#1c2530" : undefined,
            }}
            onClick={() => onSelect(node.node_id)}
          >
            <td style={styles.td}>
              <strong>{node.short_name ?? "?"}</strong>{" "}
              <span style={styles.dim}>{node.long_name ?? ""}</span>
            </td>
            <td style={{ ...styles.td, ...styles.mono }}>{node.node_id}</td>
            <td style={styles.td}>
              <span style={node.online ? styles.badgeOnline : styles.badgeOffline}>
                {node.online ? "online" : "offline"}
              </span>
            </td>
            <td style={styles.td}>
              {last_device_telemetry?.battery_level != null
                ? last_device_telemetry.battery_level > 100
                  ? "⚡ ext."
                  : `${last_device_telemetry.battery_level}%`
                : "—"}
            </td>
            <td style={styles.td}>{node.snr != null ? `${node.snr} dB` : "—"}</td>
            <td style={styles.td}>{node.hops_away ?? "—"}</td>
            <td style={{ ...styles.td, ...styles.mono }}>
              {last_position
                ? `${last_position.latitude.toFixed(4)}, ${last_position.longitude.toFixed(4)}`
                : "—"}
            </td>
            <td style={styles.td}>{relativeTime(node.last_seen_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

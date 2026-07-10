import { activeGatewayCount, type NodeSummaryOut } from "../api/client";
import { styles } from "../styles";
import { chipStyle } from "../tokens";

interface Props {
  summaries: NodeSummaryOut[];
  selected: string | null;
  /** Nodo en Focus (§7.3): su fila se resalta también aquí — sincronía visual. */
  focusId?: string | null;
  onSelect: (nodeId: string) => void;
  onToggleFavorite: (nodeId: string, value: boolean) => void;
  onToggleIgnored: (nodeId: string, value: boolean) => void;
  // Selección múltiple para batches (M2)
  checkedIds: Set<string>;
  onToggleChecked: (nodeId: string) => void;
  onToggleCheckAll: () => void;
}

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `hace ${Math.round(seconds)}s`;
  if (seconds < 3600) return `hace ${Math.round(seconds / 60)}m`;
  return `hace ${Math.round(seconds / 3600)}h`;
}

export function NodesTable({
  summaries,
  selected,
  focusId = null,
  onSelect,
  onToggleFavorite,
  onToggleIgnored,
  checkedIds,
  onToggleChecked,
  onToggleCheckAll,
}: Props) {
  const allChecked = summaries.length > 0 && summaries.every((s) => checkedIds.has(s.node.node_id));
  return (
    <table style={styles.table}>
      <thead>
        <tr>
          <th style={styles.th}>
            <input type="checkbox" checked={allChecked} onChange={onToggleCheckAll} title="Seleccionar visibles" />
          </th>
          <th style={styles.th}></th>
          <th style={styles.th}>Nodo</th>
          <th style={styles.th}>ID</th>
          <th style={styles.th}>Etiquetas</th>
          <th style={styles.th}>Estado</th>
          <th style={styles.th}>Batería</th>
          <th style={styles.th}>SNR</th>
          <th style={styles.th}>Pasarela</th>
          <th style={styles.th}>Visto</th>
          <th style={styles.th}></th>
        </tr>
      </thead>
      <tbody>
        {summaries.map((summary) => {
          const { node, last_device_telemetry, tags } = summary;
          const gwCount = activeGatewayCount(summary);
          return (
          <tr
            key={node.node_id}
            style={{
              ...styles.rowHover,
              background:
                focusId === node.node_id
                  ? "var(--accent-tint)"
                  : selected === node.node_id
                    ? "var(--surface-2)"
                    : undefined,
              boxShadow: focusId === node.node_id ? "inset 2px 0 0 var(--accent)" : undefined,
              opacity: node.is_ignored ? 0.55 : 1,
            }}
            onClick={() => onSelect(node.node_id)}
          >
            <td style={styles.td}>
              <input
                type="checkbox"
                checked={checkedIds.has(node.node_id)}
                onClick={(e) => e.stopPropagation()}
                onChange={() => onToggleChecked(node.node_id)}
              />
            </td>
            <td style={styles.td}>
              <span
                title={node.is_favorite ? "Quitar de favoritos" : "Marcar favorito"}
                style={{ cursor: "pointer", color: node.is_favorite ? "var(--warn)" : "var(--text-faint)" }}
                onClick={(e) => {
                  e.stopPropagation();
                  onToggleFavorite(node.node_id, !node.is_favorite);
                }}
              >
                {node.is_favorite ? "★" : "☆"}
              </span>
            </td>
            <td style={styles.td}>
              <strong>{node.short_name ?? "?"}</strong>{" "}
              <span style={styles.dim}>{node.long_name ?? ""}</span>
            </td>
            <td style={{ ...styles.td, ...styles.mono }}>{node.node_id}</td>
            <td style={styles.td}>
              {tags.map((t) => (
                <span
                  key={t.id}
                  style={{
                    background: t.color ?? "var(--border)",
                    borderRadius: 10,
                    padding: "0.05rem 0.5rem",
                    marginRight: 4,
                    fontSize: "0.75rem",
                  }}
                >
                  {t.name}
                </span>
              ))}
            </td>
            <td style={styles.td}>
              <span style={node.online ? styles.badgeOnline : styles.badgeOffline}>
                {node.online ? "online" : "offline"}
              </span>
              {node.is_ignored && <span style={{ ...styles.dim, marginLeft: 6 }}>(ignorado)</span>}
            </td>
            <td style={styles.td}>
              {last_device_telemetry?.battery_level != null
                ? last_device_telemetry.battery_level > 100
                  ? "⚡ ext."
                  : `${last_device_telemetry.battery_level}%`
                : "—"}
            </td>
            <td style={styles.td}>{node.snr != null ? `${node.snr} dB` : "—"}</td>
            <td style={styles.td}>
              <span style={styles.mono}>{node.gateway_id ?? "—"}</span>
              {gwCount > 1 && (
                <span
                  title={`Oído ahora mismo por ${gwCount} pasarelas — detalle en el panel del nodo`}
                  style={{
                    ...chipStyle("var(--accent)"),
                    padding: "0 0.4rem",
                    marginLeft: 6,
                    fontSize: "0.72rem",
                  }}
                >
                  🛰 {gwCount}
                </span>
              )}
            </td>
            <td style={styles.td}>{relativeTime(node.last_seen_at)}</td>
            <td style={styles.td}>
              <span
                title={node.is_ignored ? "Dejar de ignorar" : "Ignorar nodo"}
                style={{ cursor: "pointer" }}
                onClick={(e) => {
                  e.stopPropagation();
                  onToggleIgnored(node.node_id, !node.is_ignored);
                }}
              >
                {node.is_ignored ? "🚫" : "👁"}
              </span>
            </td>
          </tr>
          );
        })}
      </tbody>
    </table>
  );
}

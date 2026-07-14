import { activeGatewayCount, type NodeSummaryOut } from "../../api/client";
import { relTime } from "../../time";

/**
 * Instrumentos compartidos de una fila de Flota (v0.8, extraído en la fase
 * "Flota orientada a grupos"): la vista plana ("Toda la red") y los bloques
 * taxonómicos dentro de un grupo activo pintan exactamente la misma fila —
 * cero divergencia visual entre ambos modos.
 */

export const GRID =
  "20px 20px 14px minmax(140px,1.5fr) 92px minmax(80px,1fr) 120px 76px minmax(90px,120px) 70px 26px";

// Tráfico "reciente" para el pulso de la columna de presencia (hardening):
// la actividad es un indicador visual, nunca criterio de orden del roster.
const RECENT_SEEN_MS = 120_000;

export function Battery({
  level,
  lowThreshold = 20,
}: {
  level: number | null | undefined;
  /** Umbral de batería baja (thresholds del backend, no hardcodeado). */
  lowThreshold?: number;
}) {
  if (level == null) return <span style={{ color: "var(--text-faint)" }}>—</span>;
  if (level > 100) {
    return <span className="meter" style={{ color: "var(--ok)" }}>⚡ ext</span>;
  }
  const color = level < lowThreshold ? "var(--crit)" : level <= 50 ? "var(--warn)" : "var(--ok)";
  return (
    <span className="meter">
      <span className="track">
        <span className="fill" style={{ width: `${level}%`, background: color }} />
      </span>
      <span style={{ color }}>{level}%</span>
    </span>
  );
}

export function Signal({ snr }: { snr: number | null }) {
  if (snr == null) return <span style={{ color: "var(--text-faint)" }}>—</span>;
  const bars = snr > 5 ? 4 : snr > 0 ? 3 : snr > -7 ? 2 : snr > -15 ? 1 : 0;
  const heights = [4, 7, 10, 12];
  return (
    <span
      className={`sigbars${bars <= 2 ? " weak" : ""}`}
      title={`SNR ${snr} dB`}
      style={{ marginRight: 5 }}
    >
      {heights.map((h, i) => (
        <i key={i} className={i < bars ? "on" : undefined} style={{ height: h }} />
      ))}
    </span>
  );
}

export function RosterHead() {
  return (
    <div className="roster-head" style={{ gridTemplateColumns: GRID }}>
      <span />
      <span />
      <span />
      <span>Nodo</span>
      <span>ID</span>
      <span>Etiquetas</span>
      <span>Batería</span>
      <span>Señal</span>
      <span>Pasarela</span>
      <span>Visto</span>
      <span />
    </div>
  );
}

export function FleetRow({
  summary,
  selected,
  focusId,
  checked,
  onSelect,
  onToggleFavorite,
  onToggleIgnored,
  onToggleChecked,
  lowBatteryThreshold = 20,
}: {
  summary: NodeSummaryOut;
  selected: string | null;
  focusId: string | null;
  checked: boolean;
  onSelect: (id: string) => void;
  onToggleFavorite: (id: string, value: boolean) => void;
  onToggleIgnored: (id: string, value: boolean) => void;
  onToggleChecked: (id: string) => void;
  /** Umbral de batería baja (thresholds del backend, no hardcodeado). */
  lowBatteryThreshold?: number;
}) {
  const { node, last_device_telemetry, tags: nodeTags } = summary;
  const gwCount = activeGatewayCount(summary);
  // Actividad como INDICADOR (hardening): el roster ya no se ordena por
  // recencia — el tráfico reciente se señala con un pulso en la presencia.
  const recent =
    node.online &&
    node.last_seen_at != null &&
    Date.now() - new Date(node.last_seen_at).getTime() < RECENT_SEEN_MS;
  const cls = [
    "roster-row",
    focusId === node.node_id ? "focus" : selected === node.node_id ? "sel" : "",
    node.is_ignored ? "dim" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div
      key={node.node_id}
      className={cls}
      style={{ gridTemplateColumns: GRID }}
      onClick={() => onSelect(node.node_id)}
    >
      <span onClick={(e) => e.stopPropagation()}>
        <input type="checkbox" checked={checked} onChange={() => onToggleChecked(node.node_id)} />
      </span>
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
      <span
        className={`presence ${node.online ? "on" : "off"}${recent ? " noc-pulse" : ""}`}
        title={recent ? "En línea · tráfico en los últimos 2 min" : node.online ? "En línea" : "Offline"}
      >
        {node.online ? "●" : "○"}
      </span>
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        <strong>{node.short_name ?? "?"}</strong>{" "}
        <span style={{ color: "var(--text-dim)" }}>{node.long_name ?? ""}</span>
        {node.is_ignored && <span style={{ color: "var(--text-faint)" }}> · ignorado</span>}
      </span>
      <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>{node.node_id}</span>
      <span style={{ overflow: "hidden", whiteSpace: "nowrap" }}>
        {nodeTags.map((tag) => (
          <span
            key={tag.id}
            className="chip"
            style={{ marginRight: 4, borderColor: tag.color ?? "var(--border)", color: tag.color ?? "var(--text-dim)" }}
          >
            {tag.name}
          </span>
        ))}
      </span>
      <span>
        <Battery level={last_device_telemetry?.battery_level} lowThreshold={lowBatteryThreshold} />
      </span>
      <span>
        <Signal snr={node.snr} />
        {node.snr != null && (
          <span className="mono" style={{ fontSize: 10.5, color: "var(--text-dim)" }}>
            {node.snr}
          </span>
        )}
      </span>
      <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {node.gateway_id ?? "—"}
        {gwCount > 1 && (
          <span className="chip" style={{ marginLeft: 5, color: "var(--accent)", borderColor: "var(--accent)" }} title={`Oído por ${gwCount} pasarelas`}>
            🛰{gwCount}
          </span>
        )}
      </span>
      <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>
        {relTime(node.last_seen_at)}
      </span>
      <span
        title={node.is_ignored ? "Dejar de ignorar" : "Ignorar nodo"}
        style={{ cursor: "pointer", color: "var(--text-faint)" }}
        onClick={(e) => {
          e.stopPropagation();
          onToggleIgnored(node.node_id, !node.is_ignored);
        }}
      >
        {node.is_ignored ? "🚫" : "👁"}
      </span>
    </div>
  );
}

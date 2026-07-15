import type { ReactNode } from "react";
import { activeGatewayCount, type NodeSummaryOut } from "../../api/client";
import { relTime } from "../../time";
import { CATEGORY_DEFS, classifyNode } from "./classify";

/**
 * Instrumentos compartidos de una fila de Flota (v0.8, extraído en la fase
 * "Flota orientada a grupos"): la vista plana ("Toda la red") y los bloques
 * taxonómicos dentro de un grupo activo pintan exactamente la misma fila —
 * cero divergencia visual entre ambos modos.
 *
 * Columnas configurables (pedido del usuario): 5 columnas van SIEMPRE
 * (checkbox/favorito/presencia/nombre/id) y una al final (ignorar) — el resto
 * es una lista de columnas opcionales (`FLEET_COLUMNS`) que el operador activa
 * o desactiva con `ColumnPicker`, persistido en `usePersistedState`. El orden
 * de aparición es siempre el de `FLEET_COLUMNS`, no el orden en que se activan.
 */

export type FleetColumnId =
  | "tags"
  | "battery"
  | "signal"
  | "gateway"
  | "lastSeen"
  | "type"
  | "hardware"
  | "firmware"
  | "role"
  | "hops"
  | "mqtt"
  | "firstSeen";

interface ColumnCtx {
  gatewayNodeIds: Set<string>;
  lowBatteryThreshold: number;
}

interface FleetColumnDef {
  id: FleetColumnId;
  label: string;
  /** Track del grid (mismo formato que el resto del roster). */
  width: string;
  render: (summary: NodeSummaryOut, ctx: ColumnCtx) => ReactNode;
}

const mono: React.CSSProperties = { fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-dim)" };
const dim: React.CSSProperties = { fontSize: 11, color: "var(--text-dim)" };

export const FLEET_COLUMNS: FleetColumnDef[] = [
  {
    id: "tags",
    label: "Etiquetas",
    width: "minmax(80px,1fr)",
    render: (s) => (
      <span style={{ overflow: "hidden", whiteSpace: "nowrap" }}>
        {s.tags.map((tag) => (
          <span
            key={tag.id}
            className="chip"
            style={{ marginRight: 4, borderColor: tag.color ?? "var(--border)", color: tag.color ?? "var(--text-dim)" }}
          >
            {tag.name}
          </span>
        ))}
      </span>
    ),
  },
  {
    id: "battery",
    label: "Batería",
    width: "120px",
    render: (s, ctx) => <Battery level={s.last_device_telemetry?.battery_level} lowThreshold={ctx.lowBatteryThreshold} />,
  },
  {
    id: "signal",
    label: "Señal",
    width: "76px",
    render: (s) => (
      <>
        <Signal snr={s.node.snr} />
        {s.node.snr != null && (
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--text-dim)" }}>{s.node.snr}</span>
        )}
      </>
    ),
  },
  {
    id: "gateway",
    label: "Pasarela",
    width: "minmax(90px,120px)",
    render: (s) => {
      const gwCount = activeGatewayCount(s);
      return (
        <span style={{ ...mono, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {s.node.gateway_id ?? "—"}
          {gwCount > 1 && (
            <span className="chip" style={{ marginLeft: 5, color: "var(--accent)", borderColor: "var(--accent)" }} title={`Oído por ${gwCount} pasarelas`}>
              🛰{gwCount}
            </span>
          )}
        </span>
      );
    },
  },
  {
    id: "lastSeen",
    label: "Visto",
    width: "70px",
    render: (s) => <span style={mono}>{relTime(s.node.last_seen_at)}</span>,
  },
  {
    id: "type",
    label: "Tipo",
    width: "minmax(90px,120px)",
    render: (s, ctx) => {
      const def = CATEGORY_DEFS.find((c) => c.id === classifyNode(s, ctx.gatewayNodeIds));
      return (
        <span title={def?.label} style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {def?.icon} <span style={dim}>{def?.label}</span>
        </span>
      );
    },
  },
  {
    id: "hardware",
    label: "Hardware",
    width: "minmax(80px,110px)",
    render: (s) => <span style={{ ...mono, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.node.hw_model ?? "—"}</span>,
  },
  {
    id: "firmware",
    label: "Firmware",
    width: "90px",
    render: (s) => <span style={mono}>{s.node.firmware_version ?? "—"}</span>,
  },
  {
    id: "role",
    label: "Rol",
    width: "minmax(70px,110px)",
    render: (s) => <span style={{ ...dim, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.node.role ?? "—"}</span>,
  },
  {
    id: "hops",
    label: "Saltos",
    width: "56px",
    render: (s) => <span style={mono}>{s.node.hops_away ?? "—"}</span>,
  },
  {
    id: "mqtt",
    label: "MQTT",
    width: "56px",
    render: (s) =>
      s.node.via_mqtt ? (
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--accent)" }}>MQTT</span>
      ) : (
        <span style={{ color: "var(--text-faint)" }}>—</span>
      ),
  },
  {
    id: "firstSeen",
    label: "1ª vez",
    width: "70px",
    render: (s) => <span style={mono}>{relTime(s.node.first_seen_at)}</span>,
  },
];

export const DEFAULT_FLEET_COLUMNS: FleetColumnId[] = ["tags", "battery", "signal", "gateway", "lastSeen"];

/** Construye el `grid-template-columns` del roster: prefijo/sufijo fijos + columnas opcionales visibles, en el orden de `FLEET_COLUMNS`. */
export function buildFleetGrid(visibleColumns: FleetColumnId[]): string {
  const middle = FLEET_COLUMNS.filter((c) => visibleColumns.includes(c.id))
    .map((c) => c.width)
    .join(" ");
  return `20px 20px 14px minmax(140px,1.5fr) 92px ${middle} 26px`;
}

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

export function RosterHead({ visibleColumns }: { visibleColumns: FleetColumnId[] }) {
  return (
    <div className="roster-head" style={{ gridTemplateColumns: buildFleetGrid(visibleColumns) }}>
      <span />
      <span />
      <span />
      <span>Nodo</span>
      <span>ID</span>
      {FLEET_COLUMNS.filter((c) => visibleColumns.includes(c.id)).map((c) => (
        <span key={c.id}>{c.label}</span>
      ))}
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
  visibleColumns,
  gatewayNodeIds,
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
  visibleColumns: FleetColumnId[];
  /** Necesario para la columna "Tipo" (clasificación única, ver classify.ts). */
  gatewayNodeIds: Set<string>;
  /** Umbral de batería baja (thresholds del backend, no hardcodeado). */
  lowBatteryThreshold?: number;
}) {
  const { node } = summary;
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
  const ctx: ColumnCtx = { gatewayNodeIds, lowBatteryThreshold };
  return (
    <div
      key={node.node_id}
      className={cls}
      style={{ gridTemplateColumns: buildFleetGrid(visibleColumns) }}
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
      {FLEET_COLUMNS.filter((c) => visibleColumns.includes(c.id)).map((c) => (
        <span key={c.id} style={{ overflow: "hidden", whiteSpace: "nowrap" }}>
          {c.render(summary, ctx)}
        </span>
      ))}
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

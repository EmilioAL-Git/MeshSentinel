import type { GroupOut, MultiGatewayStatsOut } from "../../api/client";
import { fmtElapsed } from "../../time";
import { t } from "../../tokens";
import type { FleetGroupMetrics } from "./groupStats";

/**
 * Banda del grupo activo (fase "Flota orientada a grupos"): una consola no
 * necesita tarjetas — una línea de identidad + una línea de agregados,
 * ambas mono, ambas densas. Cada métrica sin dato simplemente no se pinta.
 */

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <span style={{ whiteSpace: "nowrap" }}>
      <span style={{ color: t.textFaint }}>{label} </span>
      <span className="mono" style={{ color: color ?? t.text, fontVariantNumeric: "tabular-nums" }}>{value}</span>
    </span>
  );
}

export function GroupBar({
  group,
  metrics,
  gatewayStats,
  lowBatteryThreshold = 20,
}: {
  group: GroupOut;
  metrics: FleetGroupMetrics;
  gatewayStats: MultiGatewayStatsOut | undefined;
  /** Umbral de batería baja (thresholds del backend, no hardcodeado). */
  lowBatteryThreshold?: number;
}) {
  const gatewaysVisible = gatewayStats?.gateways.filter((g) => g.nodes_visible > 0).length ?? null;

  return (
    <div
      style={{
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
        gap: "0.3rem",
        padding: "0.5rem 0.9rem",
        background: t.surface,
        borderBottom: `1px solid ${t.borderSubtle}`,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
        <span style={{ fontSize: 12, fontWeight: 650, letterSpacing: "0.06em", color: t.text }}>
          📁 {group.name.toUpperCase()}
        </span>
        <Stat label="nodos" value={String(metrics.total)} />
        <Stat label="online" value={String(metrics.online)} color={t.ok} />
        {gatewaysVisible != null && <Stat label="pasarelas" value={String(gatewaysVisible)} />}
        {metrics.criticalAlerts > 0 && (
          <Stat label="⚠" value={`${metrics.criticalAlerts} crítica${metrics.criticalAlerts !== 1 ? "s" : ""}`} color={t.crit} />
        )}
        {metrics.lastActivitySeconds != null && (
          <Stat label="actividad" value={`hace ${fmtElapsed(metrics.lastActivitySeconds)}`} />
        )}
      </div>
      <div
        className="mono"
        style={{ display: "flex", alignItems: "center", gap: "1.1rem", flexWrap: "wrap", fontSize: 11, color: t.textDim }}
      >
        {metrics.batteryAvg != null && (
          <Stat label="🔋 media" value={`${metrics.batteryAvg.toFixed(0)}%`} />
        )}
        {metrics.batteryMin != null && (
          <Stat label="mín" value={`${metrics.batteryMin.toFixed(0)}%`} color={metrics.batteryMin < lowBatteryThreshold ? t.crit : undefined} />
        )}
        {metrics.snrAvg != null && <Stat label="📶 SNR" value={`${metrics.snrAvg.toFixed(1)} dB`} />}
        {gatewayStats != null && gatewayStats.nodes_observed > 0 && (
          <Stat label="🔁 redundancia" value={`${gatewayStats.redundancy_percent}%`} />
        )}
        {metrics.temperatureAvg != null && <Stat label="🌡" value={`${metrics.temperatureAvg.toFixed(1)}°C`} />}
        {metrics.humidityAvg != null && <Stat label="💧" value={`${metrics.humidityAvg.toFixed(0)}%`} />}
        {metrics.pressureAvg != null && <Stat label="⚗" value={`${metrics.pressureAvg.toFixed(0)} hPa`} />}
      </div>
    </div>
  );
}

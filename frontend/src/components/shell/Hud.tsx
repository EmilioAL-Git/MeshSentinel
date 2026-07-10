import type { CSSProperties } from "react";
import type { AlertOut, DashboardSummaryOut, GatewayOut } from "../../api/client";
import { healthColor, t } from "../../tokens";

/**
 * HUD permanente (v0.7 §11.1): las 5 constantes vitales de la red, siempre
 * visibles en la cabecera. Exactamente cinco indicadores — salud global,
 * nodos online, gateways, alertas CRITICAL y operaciones activas — en mono
 * tabular para que no "baile" al cambiar cifras. Cada uno es clicable.
 * La variante "overlay" (modo pared/móvil) llegará con el Centro (v0.7.1+).
 */

const hudStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "0.9rem",
  fontFamily: t.fontMono,
  fontSize: 12,
  fontVariantNumeric: "tabular-nums",
  color: t.textDim,
  whiteSpace: "nowrap",
};

const itemStyle: CSSProperties = {
  background: "none",
  border: "none",
  padding: 0,
  font: "inherit",
  color: "inherit",
  cursor: "pointer",
  display: "inline-flex",
  alignItems: "center",
  gap: "0.3rem",
};

const HEALTH_LABEL: Record<string, string> = {
  HEALTHY: "OK",
  WARNING: "WARN",
  CRITICAL: "CRIT",
};

export function Hud({
  summary,
  gateways,
  alerts,
  activeOps,
  onGoTo,
}: {
  summary: DashboardSummaryOut | undefined;
  gateways: GatewayOut[];
  alerts: AlertOut[];
  activeOps: number;
  onGoTo: (view: "dashboard" | "nodes" | "gateways" | "alerts" | "operations") => void;
}) {
  const enabled = gateways.filter((g) => g.enabled && g.deleted_at == null);
  const connected = enabled.filter((g) => g.status === "connected").length;
  const criticalAlerts = alerts.filter(
    (a) => a.status !== "resolved" && a.severity === "CRITICAL",
  ).length;
  const status = summary?.status;

  return (
    <div style={hudStyle} title="Constantes vitales de la red">
      <button style={itemStyle} onClick={() => onGoTo("dashboard")} title="Salud global de la red">
        <span style={{ color: healthColor(status), fontSize: 10 }}>██</span>
        <span style={{ color: healthColor(status) }}>{status ? HEALTH_LABEL[status] : "…"}</span>
      </button>
      <button style={itemStyle} onClick={() => onGoTo("nodes")} title="Nodos online / total">
        ⬆ {summary ? `${summary.nodes_online}/${summary.nodes_total}` : "…"}
      </button>
      <button style={itemStyle} onClick={() => onGoTo("gateways")} title="Pasarelas conectadas / habilitadas">
        <span style={{ color: connected < enabled.length ? t.crit : "inherit" }}>
          ⛭ {connected}/{enabled.length}
        </span>
      </button>
      <button style={itemStyle} onClick={() => onGoTo("alerts")} title="Alertas CRITICAL activas">
        <span style={{ color: criticalAlerts > 0 ? t.crit : "inherit" }}>⚠ {criticalAlerts}</span>
      </button>
      <button style={itemStyle} onClick={() => onGoTo("operations")} title="Operaciones activas (en cola o ejecutándose)">
        ▶ {activeOps}
      </button>
    </div>
  );
}

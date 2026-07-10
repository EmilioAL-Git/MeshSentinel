import type { CSSProperties, ReactNode } from "react";
import type { AlertOut, DashboardSummaryOut, GatewayOut, OperationOut } from "../../api/client";
import { healthColor, t } from "../../tokens";

/**
 * HUD inteligente (v0.7.3): no contadores, interpretación. Cada indicador
 * lleva una línea de contexto que responde a la pregunta que provoca el
 * número ("⚠ 5" → "3 nuevas · 2 ACK"; "⛭ 1/2" → "gw-02 caída"). Sigue
 * siendo mono tabular, discreto y clicable; sigue habiendo exactamente
 * cinco indicadores.
 */

const hudStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "1.1rem",
  fontFamily: t.fontMono,
  fontVariantNumeric: "tabular-nums",
  whiteSpace: "nowrap",
};

const itemStyle: CSSProperties = {
  background: "none",
  border: "none",
  padding: 0,
  font: "inherit",
  cursor: "pointer",
  textAlign: "left",
  lineHeight: 1.25,
};

const HEALTH_LABEL: Record<string, string> = {
  HEALTHY: "OK",
  WARNING: "WARN",
  CRITICAL: "CRIT",
};

function Item({
  value,
  sub,
  subColor,
  title,
  onClick,
}: {
  value: ReactNode;
  sub: ReactNode;
  subColor?: string;
  title: string;
  onClick: () => void;
}) {
  return (
    <button style={itemStyle} onClick={onClick} title={title}>
      <div style={{ color: t.textDim, fontSize: 12 }}>{value}</div>
      <div style={{ color: subColor ?? t.textFaint, fontSize: 9.5 }}>{sub}</div>
    </button>
  );
}

export function Hud({
  summary,
  gateways,
  alerts,
  operations,
  onGoTo,
}: {
  summary: DashboardSummaryOut | undefined;
  gateways: GatewayOut[];
  alerts: AlertOut[];
  operations: OperationOut[];
  onGoTo: (view: "ops" | "nodes" | "gateways" | "alerts" | "jobs") => void;
}) {
  const enabled = gateways.filter((g) => g.enabled && g.deleted_at == null);
  const down = enabled.filter((g) => g.status !== "connected");

  const active = alerts.filter((a) => a.status !== "resolved");
  const firing = active.filter((a) => a.status === "firing").length;
  const acked = active.length - firing;
  const hasCrit = active.some((a) => a.severity === "CRITICAL");
  const alertColor = active.length === 0 ? t.textDim : hasCrit ? t.crit : t.warn;

  const running = operations.filter((o) => o.status === "running").length;
  const queued = operations.filter((o) => o.status === "pending" || o.status === "queued").length;

  const status = summary?.status;
  // Interpretación de la salud: el primer motivo que la explica, no otro número
  const healthSub = !summary
    ? "…"
    : down.length > 0
      ? `${down.length} pasarela(s) caída(s)`
      : status !== "HEALTHY" && summary.nodes_offline > 0
        ? `${summary.nodes_offline} nodos offline`
        : status !== "HEALTHY" && summary.low_battery_count > 0
          ? `${summary.low_battery_count} baterías bajas`
          : "red estable";

  return (
    <div style={hudStyle} title="Constantes vitales de la red">
      <Item
        title="Salud global de la red"
        onClick={() => onGoTo("ops")}
        value={
          <span style={{ color: healthColor(status) }}>
            <span style={{ fontSize: 10 }}>██</span> {status ? HEALTH_LABEL[status] : "…"}
          </span>
        }
        sub={healthSub}
        subColor={status && status !== "HEALTHY" ? healthColor(status) : undefined}
      />
      <Item
        title="Nodos online / total (sin ignorados)"
        onClick={() => onGoTo("nodes")}
        value={<>⬆ {summary ? `${summary.nodes_online}/${summary.nodes_total}` : "…"}</>}
        sub={summary ? (summary.nodes_offline > 0 ? `${summary.nodes_offline} offline` : "todos online") : "…"}
      />
      <Item
        title="Pasarelas conectadas / habilitadas"
        onClick={() => onGoTo("gateways")}
        value={
          <span style={{ color: down.length > 0 ? t.crit : t.textDim }}>
            ⛭ {enabled.length - down.length}/{enabled.length}
          </span>
        }
        sub={down.length === 0 ? "conectadas" : `${down[0].gateway_id} caída${down.length > 1 ? ` +${down.length - 1}` : ""}`}
        subColor={down.length > 0 ? t.crit : undefined}
      />
      <Item
        title="Alertas activas (nuevas = sin reconocer)"
        onClick={() => onGoTo("alerts")}
        value={<span style={{ color: alertColor }}>⚠ {active.length}</span>}
        sub={active.length === 0 ? "sin alertas" : `${firing} nuevas · ${acked} ACK`}
        subColor={active.length > 0 ? alertColor : undefined}
      />
      <Item
        title="Operaciones de administración remota"
        onClick={() => onGoTo("jobs")}
        value={<>▶ {running + queued}</>}
        sub={running + queued === 0 ? "inactivo" : `${running} activa(s) · ${queued} en cola`}
      />
    </div>
  );
}

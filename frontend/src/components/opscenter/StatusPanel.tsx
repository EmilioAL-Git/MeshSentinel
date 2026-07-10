import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { CSSProperties } from "react";
import {
  ackAlert,
  type AlertOut,
  type CriticalReason,
  type DashboardSummaryOut,
  type GatewayOut,
  type MultiGatewayStatsOut,
} from "../../api/client";
import { relativeTime } from "../../time";
import { healthColor, t } from "../../tokens";
import { BlockAccordion } from "../shell/BlockAccordion";

/**
 * Panel izquierdo del Centro de Operaciones (v0.7 §4): SOLO estado, de
 * arriba abajo por criticidad — semáforo, alertas (con ACK inline, primer
 * uso del endpoint de 3C), gateways y nodos en atención. Sobre lo que hay
 * que ACTUAR (ops/lotes) vive en la consola derecha (§5.3 del diseño).
 */

const HEALTH_LABEL: Record<string, string> = {
  HEALTHY: "OPERATIVA",
  WARNING: "DEGRADADA",
  CRITICAL: "CRÍTICA",
};

const REASON_ICON: Record<CriticalReason, string> = {
  low_battery: "🔋",
  inactive: "📴",
  degraded_snr: "📶",
};

const rowStyle: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  gap: "0.45rem",
  padding: "0.18rem 0",
  fontSize: 12.5,
};

const linkBtn: CSSProperties = {
  background: "none",
  border: "none",
  color: t.accent,
  cursor: "pointer",
  font: "inherit",
  fontSize: 12,
  padding: 0,
};

const smallBtn: CSSProperties = {
  background: "transparent",
  border: `1px solid ${t.border}`,
  color: t.text,
  borderRadius: 4,
  cursor: "pointer",
  fontSize: 11,
  padding: "0 0.45rem",
};

function GoTo({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button style={linkBtn} onClick={(e) => { e.stopPropagation(); onClick(); }}>
      {label}
    </button>
  );
}

/** Motivos legibles del estado ≠HEALTHY, derivados de los agregados que ya
 * calcula el backend con sus umbrales (dashboard/summary). */
function healthReasons(s: DashboardSummaryOut, gateways: GatewayOut[]): string[] {
  const reasons: string[] = [];
  const gwEnabled = gateways.filter((g) => g.enabled && g.deleted_at == null);
  const gwDown = gwEnabled.filter((g) => g.status !== "connected");
  if (gwDown.length > 0) reasons.push(`${gwDown.length} pasarela(s) sin conexión`);
  if (s.nodes_offline > 0 && s.offline_percent >= s.thresholds.offline_percent_warning) {
    reasons.push(`${s.nodes_offline} nodos offline (${Math.round(s.offline_percent)} %)`);
  }
  if (s.low_battery_count > 0) {
    reasons.push(`${s.low_battery_count} nodo(s) con batería < ${s.thresholds.low_battery_percent} %`);
  }
  return reasons;
}

export function StatusPanel({
  summary,
  alerts,
  gateways,
  stats,
  onOpenNode,
  onGoTo,
}: {
  summary: DashboardSummaryOut | undefined;
  alerts: AlertOut[];
  gateways: GatewayOut[];
  stats: MultiGatewayStatsOut | undefined;
  onOpenNode: (nodeId: string) => void;
  onGoTo: (view: string) => void;
}) {
  const queryClient = useQueryClient();
  const doAck = useMutation({
    mutationFn: (id: number) => ackAlert(id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });

  const active = alerts
    .filter((a) => a.status !== "resolved")
    .sort((a, b) => {
      const rank = (x: AlertOut) => (x.severity === "CRITICAL" ? 0 : x.severity === "WARNING" ? 1 : 2);
      return rank(a) - rank(b) || (a.fired_at < b.fired_at ? 1 : -1);
    });

  const gwRows = gateways.filter((g) => g.enabled && g.deleted_at == null);
  const gwConnected = gwRows.filter((g) => g.status === "connected").length;
  const statsById = new Map((stats?.gateways ?? []).map((g) => [g.gateway_id, g]));
  const attention = summary?.critical_nodes ?? [];
  const reasons = summary && summary.status !== "HEALTHY" ? healthReasons(summary, gateways) : [];

  return (
    <div style={{ display: "flex", flexDirection: "column", overflowY: "auto", height: "100%" }}>
      {/* ① Semáforo de red: única superficie grande teñida de color (§4.1).
          Con estado ≠HEALTHY los motivos aparecen YA expandidos: 0 clics. */}
      <section
        style={{
          background: `color-mix(in srgb, ${healthColor(summary?.status)} 12%, transparent)`,
          borderBottom: `1px solid ${t.borderSubtle}`,
          borderLeft: `3px solid ${healthColor(summary?.status)}`,
          padding: "0.7rem 0.9rem",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: "0.5rem" }}>
          <span style={{ color: healthColor(summary?.status), fontWeight: 700, fontSize: 14, letterSpacing: "0.05em" }}>
            RED {summary ? HEALTH_LABEL[summary.status] : "…"}
          </span>
        </div>
        <div style={{ color: t.textDim, fontSize: 12, fontFamily: t.fontMono, fontVariantNumeric: "tabular-nums" }}>
          {summary
            ? `${summary.nodes_online}/${summary.nodes_total} online · ${attention.length} en atención`
            : "cargando…"}
        </div>
        {reasons.map((r) => (
          <div key={r} style={{ color: t.textDim, fontSize: 12, marginTop: 2 }}>
            › {r}
          </div>
        ))}
      </section>

      {/* ② Alertas activas (prioridad visual 1) */}
      <BlockAccordion
        id="alerts"
        title="Alertas activas"
        icon="⚠"
        count={active.length}
        countColor={active.some((a) => a.severity === "CRITICAL") ? t.crit : t.warn}
        emptyLabel="Sin alertas activas."
        action={<GoTo label="Ver todas →" onClick={() => onGoTo("alerts")} />}
      >
        {active.slice(0, 5).map((a) => {
          const color = a.severity === "CRITICAL" ? t.crit : a.severity === "WARNING" ? t.warn : t.textDim;
          return (
            <div key={a.id} style={{ ...rowStyle, alignItems: "flex-start" }}>
              <span style={{ color, fontSize: 10, lineHeight: "18px" }}>●</span>
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{ color: t.text }}>{a.message}</span>{" "}
                <span style={{ color: t.textFaint, fontSize: 11 }}>
                  {relativeTime(a.fired_at)}
                  {a.status === "acknowledged" && " · ACK"}
                </span>
              </span>
              {a.status === "firing" && (
                <button style={smallBtn} title="Reconocer la alerta" disabled={doAck.isPending} onClick={() => doAck.mutate(a.id)}>
                  ACK
                </button>
              )}
              {a.subject_type === "node" && (
                <button style={smallBtn} title="Abrir el nodo" onClick={() => onOpenNode(a.subject_id)}>
                  →
                </button>
              )}
            </div>
          );
        })}
        {active.length > 5 && (
          <div style={{ color: t.textFaint, fontSize: 11.5, paddingTop: 2 }}>… y {active.length - 5} más</div>
        )}
      </BlockAccordion>

      {/* ③ Gateways */}
      <BlockAccordion
        id="gateways"
        title={`Gateways (${gwConnected}/${gwRows.length})`}
        icon="⛭"
        action={<GoTo label="Gestionar →" onClick={() => onGoTo("gateways")} />}
      >
        {gwRows.map((g) => {
          const st = statsById.get(g.gateway_id);
          const dotColor =
            g.status === "connected" ? t.ok : g.status === "connecting" || g.status === "reconnecting" ? t.warn : t.crit;
          return (
            <div key={g.gateway_id} style={{ padding: "0.18rem 0", fontSize: 12.5 }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: "0.45rem" }}>
                <span style={{ color: dotColor, fontSize: 10 }}>●</span>
                <span style={{ fontFamily: t.fontMono }}>{g.gateway_id}</span>
                <span style={{ color: t.textDim }}>{g.transport_type ?? g.transport}</span>
                {g.local_short_name && <span style={{ color: t.textDim }}>{g.local_short_name}</span>}
              </div>
              <div style={{ color: t.textFaint, fontSize: 11.5, paddingLeft: "1.05rem", fontFamily: t.fontMono }}>
                {st ? `${st.nodes_visible} nodos · ${st.nodes_exclusive} excl` : g.status}
                {" · "}
                {relativeTime(g.updated_at)}
              </div>
            </div>
          );
        })}
        {gwRows.length === 0 && <div style={{ color: t.textFaint, fontSize: 12 }}>Sin pasarelas configuradas.</div>}
        {stats && stats.gateways.length > 1 && (
          <div style={{ color: t.textDim, fontSize: 11.5, paddingTop: 4, borderTop: `1px solid ${t.borderSubtle}`, marginTop: 4 }}>
            Redundancia: {stats.nodes_shared}/{stats.nodes_observed} nodos con ≥2 pasarelas (
            {Math.round(stats.redundancy_percent)} %)
          </div>
        )}
      </BlockAccordion>

      {/* ④ Nodos que requieren atención */}
      <BlockAccordion
        id="attention"
        title="Atención"
        icon="◎"
        count={attention.length}
        emptyLabel="Ningún nodo requiere atención."
      >
        {attention.slice(0, 6).map((n) => (
          <div key={n.node_id} style={rowStyle}>
            <span title={n.reasons.join(", ")}>{n.reasons.map((r) => REASON_ICON[r]).join("")}</span>
            <span style={{ color: t.text, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {n.short_name ?? n.node_id}
            </span>
            <span style={{ color: t.textFaint, fontFamily: t.fontMono, fontSize: 11.5 }}>
              {n.battery_level != null && n.reasons.includes("low_battery")
                ? `${n.battery_level} %`
                : n.reasons.includes("degraded_snr") && n.snr != null
                  ? `${n.snr} dB`
                  : relativeTime(n.last_seen_at)}
            </span>
            <button style={smallBtn} title="Abrir el nodo" onClick={() => onOpenNode(n.node_id)}>
              →
            </button>
          </div>
        ))}
        {attention.length > 6 && (
          <div style={{ color: t.textFaint, fontSize: 11.5, paddingTop: 2 }}>… y {attention.length - 6} más</div>
        )}
      </BlockAccordion>
    </div>
  );
}

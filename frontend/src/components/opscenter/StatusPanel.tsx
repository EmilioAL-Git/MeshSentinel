import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, type CSSProperties, type ReactNode } from "react";
import {
  ackAlert,
  fetchGatewayStats,
  type AlertOut,
  type CriticalNodeOut,
  type DashboardSummaryOut,
  type GatewayOut,
  type MultiGatewayStatsOut,
  type NodeSummaryOut,
} from "../../api/client";
import { scopeAlertsToGroup, useActiveGroup, useGroupNodeIds } from "../../context/GroupContext";
import { computeFleetGroupMetrics, computeGroupAttention, computeGroupStatus, scopeGatewaysToGroup } from "../fleet/groupStats";
import { buildSituationNarrative } from "./situation";
import { relativeTime } from "../../time";
import { alertSeverityColor, healthColor, t } from "../../tokens";

/**
 * Centro de Situación consolidado (fase "consolidación del Centro"): TRES
 * secciones planas, sin acordeones, de arriba abajo por criticidad —
 *
 *   ① SITUACIÓN  — semáforo + la narrativa "qué está ocurriendo" fusionada
 *                  (antes eran dos bloques que contaban lo mismo dos veces).
 *   ② ATENCIÓN   — LA cola única: cada nodo aparece UNA vez con TODOS sus
 *                  problemas (batería/offline/SNR) y sus alertas (ACK
 *                  inline) en la misma tarjeta; las alertas de pasarela/
 *                  sistema son tarjetas propias de la misma cola. Sustituye
 *                  al bloque de alertas + Atención + los 5 destacados.
 *   ③ GATEWAYS   — estado y cobertura por pasarela (información única).
 *
 * El panel "Alertas" del riel derecho desapareció (OpsCenter): una sola
 * lista de alertas por pantalla. Categorías y destacados viven en Flota.
 */

const HEALTH_LABEL: Record<string, string> = {
  HEALTHY: "OPERATIVA",
  WARNING: "DEGRADADA",
  CRITICAL: "CRÍTICA",
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
  fontSize: 11.5,
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
  flexShrink: 0,
};

/** Cabecera de sección plana (sin acordeón): rótulo + contador + acción. */
function SectionHead({
  title,
  count,
  countColor,
  action,
}: {
  title: string;
  count?: number;
  countColor?: string;
  action?: ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        gap: 8,
        padding: "0.55rem 0.9rem 0.25rem",
      }}
    >
      <span style={{ color: t.textDim, fontSize: 10.5, letterSpacing: "0.1em", fontWeight: 650 }}>{title}</span>
      {count != null && (
        <span style={{ color: countColor ?? t.textFaint, fontFamily: t.fontMono, fontSize: 11 }}>{count}</span>
      )}
      <span style={{ marginLeft: "auto" }}>{action}</span>
    </div>
  );
}

// ── Cola de atención unificada ───────────────────────────────────────────────

interface AttentionCard {
  key: string;
  nodeId: string | null;
  label: string;
  /** 0 = crítico (alerta CRITICAL), 1 = atención (alerta o ≥2 problemas), 2 = aviso. */
  rank: number;
  /** Chips de problema derivados de umbrales: 🔋/📴/📶 con su valor. */
  problems: string[];
  alerts: AlertOut[];
}

function reasonChips(n: CriticalNodeOut): string[] {
  const chips: string[] = [];
  for (const r of n.reasons) {
    if (r === "low_battery" && n.battery_level != null) chips.push(`🔋 ${n.battery_level} %`);
    else if (r === "inactive") chips.push(`📴 ${relativeTime(n.last_seen_at)}`);
    else if (r === "degraded_snr" && n.snr != null) chips.push(`📶 ${n.snr} dB`);
  }
  return chips;
}

function buildAttentionQueue(
  attention: CriticalNodeOut[],
  activeAlerts: AlertOut[],
  labelOf: (nodeId: string) => string,
): AttentionCard[] {
  const alertsByNode = new Map<string, AlertOut[]>();
  const otherAlerts: AlertOut[] = [];
  for (const a of activeAlerts) {
    if (a.subject_type === "node") {
      const list = alertsByNode.get(a.subject_id) ?? [];
      list.push(a);
      alertsByNode.set(a.subject_id, list);
    } else {
      otherAlerts.push(a);
    }
  }

  const byNode = new Map<string, AttentionCard>();
  for (const n of attention) {
    byNode.set(n.node_id, {
      key: `node-${n.node_id}`,
      nodeId: n.node_id,
      label: labelOf(n.node_id),
      rank: 2,
      problems: reasonChips(n),
      alerts: [],
    });
  }
  // Nodos con alerta activa pero sin problema de umbral: también son la cola
  for (const [nodeId, list] of alertsByNode) {
    const card = byNode.get(nodeId) ?? {
      key: `node-${nodeId}`,
      nodeId,
      label: labelOf(nodeId),
      rank: 2,
      problems: [],
      alerts: [],
    };
    card.alerts = list;
    byNode.set(nodeId, card);
  }

  const cards = [...byNode.values()];
  // Alertas de pasarela/sistema: tarjetas propias en la MISMA cola
  for (const a of otherAlerts) {
    cards.push({
      key: `alert-${a.id}`,
      nodeId: null,
      label: `⛭ ${a.subject_id}`,
      rank: 2,
      problems: [],
      alerts: [a],
    });
  }
  for (const c of cards) {
    c.rank = c.alerts.some((a) => a.severity === "CRITICAL")
      ? 0
      : c.alerts.length > 0 || c.problems.length >= 2
        ? 1
        : 2;
  }
  return cards;
}

const RANK_COLOR = [t.crit, t.warn, t.textDim];

export function StatusPanel({
  summaries,
  summary,
  alerts,
  gateways,
  stats,
  focusId,
  onOpenNode,
  onGoTo,
}: {
  summaries: NodeSummaryOut[];
  summary: DashboardSummaryOut | undefined;
  alerts: AlertOut[];
  gateways: GatewayOut[];
  stats: MultiGatewayStatsOut | undefined;
  focusId: string | null;
  onOpenNode: (nodeId: string) => void;
  onGoTo: (view: string) => void;
}) {
  const queryClient = useQueryClient();
  const doAck = useMutation({
    mutationFn: (id: number) => ackAlert(id),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
      queryClient.invalidateQueries({ queryKey: ["alert-counts"] });
    },
  });

  // Grupo activo: mismo escopado que el resto de la app (groupStats.ts).
  const { activeGroup, clearActiveGroup } = useActiveGroup();
  const groupNodeIds = useGroupNodeIds(summaries);
  const groupSummaries = useMemo(
    () => (groupNodeIds == null ? [] : summaries.filter((s) => groupNodeIds.has(s.node.node_id))),
    [summaries, groupNodeIds],
  );
  const groupGwStats = useQuery({
    queryKey: ["gateway-stats", "group", activeGroup?.id ?? null],
    queryFn: () => fetchGatewayStats(activeGroup!.id),
    enabled: activeGroup != null,
    refetchInterval: 30_000,
  });
  const groupMetrics = useMemo(
    () => (groupNodeIds == null ? null : computeFleetGroupMetrics(groupSummaries, alerts)),
    [groupNodeIds, groupSummaries, alerts],
  );
  const attentionBase = useMemo<CriticalNodeOut[]>(
    () =>
      groupNodeIds != null && summary != null
        ? computeGroupAttention(groupSummaries, summary.thresholds)
        : (summary?.critical_nodes ?? []),
    [groupNodeIds, groupSummaries, summary],
  );

  const { inScope: scopedActive, outOfGroupCritical } = scopeAlertsToGroup(
    alerts.filter((a) => a.status !== "resolved"),
    groupNodeIds,
  );

  // Nombre completo para las tarjetas (long_name > short_name > id)
  const labelOf = useMemo(() => {
    const names = new Map<string, string>();
    for (const s of summaries) {
      const name = s.node.long_name ?? s.node.short_name;
      if (name) names.set(s.node.node_id, name);
    }
    return (nodeId: string) => names.get(nodeId) ?? nodeId;
  }, [summaries]);

  // ② LA cola de atención: cada nodo UNA vez con todos sus problemas
  const queue = useMemo(() => {
    const cards = buildAttentionQueue(attentionBase, scopedActive, labelOf);
    cards.sort(
      (a, b) =>
        Number(b.nodeId === focusId) - Number(a.nodeId === focusId) ||
        a.rank - b.rank ||
        a.label.localeCompare(b.label),
    );
    return cards;
  }, [attentionBase, scopedActive, labelOf, focusId]);
  const critCount = queue.filter((c) => c.rank === 0).length;

  const activeGwStats = groupNodeIds != null ? groupGwStats.data : stats;
  const statsById = new Map((activeGwStats?.gateways ?? []).map((g) => [g.gateway_id, g]));
  const gwRows = useMemo(
    () => scopeGatewaysToGroup(gateways, groupNodeIds, groupGwStats.data),
    [gateways, groupNodeIds, groupGwStats.data],
  );
  const gwConnected = gwRows.filter((g) => g.status === "connected").length;
  const gwDownCount = gwRows.filter(
    (g) => g.status !== "connected" && g.status !== "connecting" && g.status !== "reconnecting",
  ).length;
  const gwDegradedCount = gwRows.filter((g) => g.status === "connecting" || g.status === "reconnecting").length;

  const groupStatus = computeGroupStatus(groupMetrics?.criticalAlerts ?? 0, attentionBase.length);
  const headerStatus = groupNodeIds != null ? groupStatus : summary?.status;

  // ① Narrativa fusionada en el semáforo (antes bloque aparte "Qué está
  // ocurriendo" — misma fuente de datos, dos redacciones).
  const narrative =
    summary == null
      ? []
      : groupNodeIds != null
        ? buildSituationNarrative({
            scopeLabel: activeGroup?.name ?? "el grupo",
            nodesTotal: groupMetrics?.total ?? 0,
            attentionCount: attentionBase.length,
            gatewaysDown: gwDownCount,
            gatewaysDegraded: gwDegradedCount,
            offlinePercent:
              groupMetrics && groupMetrics.total > 0
                ? (100 * (groupMetrics.total - groupMetrics.online)) / groupMetrics.total
                : 0,
            offlinePercentWarning: summary.thresholds.offline_percent_warning,
            lowBatteryCount: attentionBase.filter((n) => n.reasons.includes("low_battery")).length,
            lowBatteryThreshold: summary.thresholds.low_battery_percent,
            snrAvg: groupMetrics?.snrAvg ?? null,
            snrDegradedThreshold: summary.thresholds.snr_degraded_db,
            channelUtilizationAvg: groupMetrics?.channelUtilizationAvg ?? null,
            redundancyPercent: groupGwStats.data?.redundancy_percent ?? null,
            avgSecondsSinceLastSeen: groupMetrics?.lastActivitySeconds ?? null,
            nodeOfflineAfterSeconds: summary.thresholds.node_offline_after_seconds,
          })
        : buildSituationNarrative({
            scopeLabel: "la red",
            nodesTotal: summary.nodes_total,
            attentionCount: attentionBase.length,
            gatewaysDown: gwDownCount,
            gatewaysDegraded: gwDegradedCount,
            offlinePercent: summary.offline_percent,
            offlinePercentWarning: summary.thresholds.offline_percent_warning,
            lowBatteryCount: summary.low_battery_count,
            lowBatteryThreshold: summary.thresholds.low_battery_percent,
            snrAvg: summary.avg_snr,
            snrDegradedThreshold: summary.thresholds.snr_degraded_db,
            channelUtilizationAvg: summary.avg_channel_utilization,
            redundancyPercent: stats?.redundancy_percent ?? null,
            avgSecondsSinceLastSeen: summary.avg_seconds_since_last_seen,
            nodeOfflineAfterSeconds: summary.thresholds.node_offline_after_seconds,
          });

  return (
    <div style={{ display: "flex", flexDirection: "column", overflowY: "auto", height: "100%" }}>
      {/* ① SITUACIÓN — semáforo + narrativa fusionada, 0 clics */}
      <section
        style={{
          background: `color-mix(in srgb, ${healthColor(headerStatus)} 12%, transparent)`,
          borderBottom: `1px solid ${t.borderSubtle}`,
          borderLeft: `3px solid ${healthColor(headerStatus)}`,
          padding: "0.7rem 0.9rem",
        }}
      >
        {activeGroup != null && (
          <div style={{ color: t.accent, fontSize: 10.5, fontWeight: 650, letterSpacing: "0.1em", marginBottom: 2 }}>
            📁 GRUPO: {activeGroup.name.toUpperCase()}{" "}
            <button style={{ ...linkBtn, fontSize: 10.5 }} onClick={clearActiveGroup}>
              · ver toda la red
            </button>
          </div>
        )}
        <div style={{ color: healthColor(headerStatus), fontWeight: 700, fontSize: 15, letterSpacing: "0.05em" }}>
          {groupNodeIds != null ? activeGroup?.name.toUpperCase() : "RED"}{" "}
          {headerStatus ? HEALTH_LABEL[headerStatus] : "…"}
        </div>
        <div style={{ color: t.textDim, fontSize: 12, fontFamily: t.fontMono, fontVariantNumeric: "tabular-nums", marginTop: 2 }}>
          {groupMetrics != null
            ? `${groupMetrics.online}/${groupMetrics.total} online · ${queue.length} en atención`
            : summary
              ? `${summary.nodes_online}/${summary.nodes_total} online · ${queue.length} en atención`
              : "cargando…"}
        </div>
        <div style={{ color: t.textDim, fontSize: 11.5, marginTop: 3, fontFamily: t.fontMono }}>
          {groupMetrics != null ? (
            <>
              {groupMetrics.batteryAvg != null && <>🔋 {groupMetrics.batteryAvg.toFixed(0)}% med</>}
              {groupMetrics.snrAvg != null && <> · 📶 {groupMetrics.snrAvg.toFixed(1)} dB</>}
              {groupMetrics.channelUtilizationAvg != null && <> · 📡 {groupMetrics.channelUtilizationAvg.toFixed(0)}% canal</>}
              {activeGwStats != null && activeGwStats.nodes_observed > 0 && (
                <> · 🔁 {activeGwStats.redundancy_percent}%</>
              )}
            </>
          ) : (
            summary != null && (
              <>
                {summary.avg_battery_percent != null && <>🔋 {summary.avg_battery_percent.toFixed(0)}% med</>}
                {summary.avg_snr != null && <> · 📶 {summary.avg_snr.toFixed(1)} dB</>}
                {summary.avg_channel_utilization != null && <> · 📡 {summary.avg_channel_utilization.toFixed(0)}% canal</>}
                {stats != null && stats.nodes_observed > 0 && <> · 🔁 {stats.redundancy_percent}%</>}
              </>
            )
          )}
        </div>
        {narrative.map((line) => (
          <div key={line} style={{ color: t.text, fontSize: 12, marginTop: 3 }}>
            › {line}
          </div>
        ))}
      </section>

      {/* ② ATENCIÓN — la cola única */}
      <section style={{ borderBottom: `1px solid ${t.borderSubtle}`, paddingBottom: 6 }}>
        <SectionHead
          title="ATENCIÓN"
          count={queue.length}
          countColor={critCount > 0 ? t.crit : queue.length > 0 ? t.warn : t.ok}
          action={<button style={linkBtn} onClick={() => onGoTo("alerts")}>Alertas →</button>}
        />
        {queue.length === 0 && (
          <div style={{ color: t.ok, fontSize: 12.5, padding: "0.15rem 0.9rem" }}>
            ✓ Nada requiere atención.
          </div>
        )}
        {queue.slice(0, 10).map((c) => (
          <div
            key={c.key}
            style={{
              margin: "0 0.6rem 5px 0.7rem",
              padding: "0.35rem 0.55rem",
              border: `1px solid ${t.borderSubtle}`,
              borderLeft: `3px solid ${RANK_COLOR[c.rank]}`,
              borderRadius: 5,
              background: c.nodeId === focusId ? t.accentTint : t.surface,
              fontSize: 12.5,
            }}
          >
            <div style={{ display: "flex", alignItems: "baseline", gap: 6, minWidth: 0 }}>
              {c.nodeId != null && c.nodeId === focusId && <span style={{ color: t.accent }}>◎</span>}
              <span
                onClick={c.nodeId ? () => onOpenNode(c.nodeId!) : undefined}
                title={c.nodeId ? "Abrir el nodo en el Inspector" : undefined}
                style={{
                  color: t.text,
                  fontWeight: 600,
                  cursor: c.nodeId ? "pointer" : "default",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {c.label}
              </span>
              {c.problems.length > 0 && (
                <span style={{ color: t.textDim, fontFamily: t.fontMono, fontSize: 11.5, marginLeft: "auto", flexShrink: 0 }}>
                  {c.problems.join(" · ")}
                </span>
              )}
            </div>
            {c.alerts.map((a) => (
              <div key={a.id} style={{ ...rowStyle, fontSize: 12, paddingLeft: 2 }}>
                <span style={{ color: alertSeverityColor(a.severity), fontSize: 9, lineHeight: "17px" }}>●</span>
                <span style={{ flex: 1, minWidth: 0, color: t.textDim }}>
                  {a.message}{" "}
                  <span style={{ color: t.textFaint, fontSize: 11 }}>
                    {relativeTime(a.fired_at)}
                    {a.status === "acknowledged" && " · ACK"}
                  </span>
                  {outOfGroupCritical.has(a.id) && (
                    <span className="chip" style={{ marginLeft: 5, color: t.warn, borderColor: t.warn, fontSize: 10 }}>
                      fuera del grupo
                    </span>
                  )}
                </span>
                {a.status === "firing" && (
                  <button style={smallBtn} title="Reconocer la alerta" disabled={doAck.isPending} onClick={() => doAck.mutate(a.id)}>
                    ACK
                  </button>
                )}
              </div>
            ))}
          </div>
        ))}
        {queue.length > 10 && (
          <div style={{ color: t.textFaint, fontSize: 11.5, padding: "0 0.9rem" }}>… y {queue.length - 10} más</div>
        )}
      </section>

      {/* ③ GATEWAYS */}
      <section style={{ paddingBottom: 8 }}>
        <SectionHead
          title="GATEWAYS"
          count={gwRows.length}
          countColor={gwConnected < gwRows.length ? t.warn : t.textFaint}
          action={<button style={linkBtn} onClick={() => onGoTo("gateways")}>Gestionar →</button>}
        />
        <div style={{ padding: "0 0.9rem" }}>
          {gwRows.map((g) => {
            const st = statsById.get(g.gateway_id);
            const dotColor =
              g.status === "connected" ? t.ok : g.status === "connecting" || g.status === "reconnecting" ? t.warn : t.crit;
            return (
              <div key={g.gateway_id} style={{ padding: "0.18rem 0", fontSize: 12.5 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: "0.45rem" }}>
                  <span style={{ color: dotColor, fontSize: 10 }}>●</span>
                  <span style={{ fontFamily: t.fontMono }}>{g.name ?? g.gateway_id}</span>
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
          {gwRows.length === 0 && (
            <div style={{ color: t.textFaint, fontSize: 12 }}>
              {groupNodeIds == null ? "Sin pasarelas configuradas." : "Ninguna pasarela ve tráfico de este grupo ahora mismo."}
            </div>
          )}
          {activeGwStats && activeGwStats.gateways.length > 1 && (
            <div style={{ color: t.textDim, fontSize: 11.5, paddingTop: 4, borderTop: `1px solid ${t.borderSubtle}`, marginTop: 4 }}>
              Redundancia: {activeGwStats.nodes_shared}/{activeGwStats.nodes_observed} nodos con ≥2 pasarelas (
              {Math.round(activeGwStats.redundancy_percent)} %)
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

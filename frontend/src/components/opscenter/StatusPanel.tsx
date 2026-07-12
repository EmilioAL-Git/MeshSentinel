import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, type CSSProperties } from "react";
import {
  ackAlert,
  fetchGatewayStats,
  type AlertOut,
  type CriticalReason,
  type DashboardSummaryOut,
  type GatewayOut,
  type MultiGatewayStatsOut,
  type NodeSummaryOut,
} from "../../api/client";
import { scopeAlertsToGroup, useActiveGroup, useGroupNodeIds } from "../../context/GroupContext";
import { CATEGORY_DEFS, groupByCategory } from "../fleet/classify";
import { computeFleetGroupMetrics, computeGroupAttention, computeGroupStatus, scopeGatewaysToGroup } from "../fleet/groupStats";
import { lowestBattery, mostActive, mostObserved, noTraffic, offline as offlineHighlights, type HighlightNode } from "./highlights";
import { buildSituationNarrative } from "./situation";
import { relativeTime } from "../../time";
import { alertSeverityColor, healthColor, t } from "../../tokens";
import { BlockAccordion } from "../shell/BlockAccordion";

/**
 * Centro de Situación del Centro de Operaciones (v0.9 Fase A): de arriba
 * abajo por criticidad — semáforo enriquecido, "qué está ocurriendo"
 * (interpretación por reglas), alertas (con ACK inline), gateways, nodos
 * en atención, distribución por categorías (solo con grupo activo,
 * `classify.ts`) y paneles de nodos destacados (`highlights.ts`). Sobre lo
 * que hay que ACTUAR (ops/lotes) vive en la consola derecha (§5.3 del
 * diseño v0.7). Todo cálculo se reutiliza de `dashboard.py`/
 * `gateway_stats.py` (red completa) o `groupStats.ts`/`classify.ts`
 * (grupo activo) — cero agregación nueva aquí.
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

function HighlightRow({
  n,
  focusId,
  onOpenNode,
}: {
  n: HighlightNode;
  focusId: string | null;
  onOpenNode: (nodeId: string) => void;
}) {
  return (
    <div style={{ ...rowStyle, background: n.node_id === focusId ? t.accentTint : undefined }}>
      <span style={{ color: t.text, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {n.node_id === focusId && <span style={{ color: t.accent }}>◎ </span>}
        {n.short_name ?? n.node_id}
      </span>
      <span style={{ color: t.textFaint, fontFamily: t.fontMono, fontSize: 11.5 }}>{n.metricLabel}</span>
      <button style={smallBtn} title="Abrir el nodo" onClick={() => onOpenNode(n.node_id)}>
        →
      </button>
    </div>
  );
}

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
  summaries,
  gatewayNodeIds,
  summary,
  alerts,
  gateways,
  stats,
  focusId,
  onOpenNode,
  onGoTo,
}: {
  summaries: NodeSummaryOut[];
  gatewayNodeIds: Set<string>;
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
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });

  // Grupo activo ("Grupo como contexto global", fase 3): el StatusPanel dice
  // de qué red habla. Reutiliza GroupBar/groupStats.ts tal cual — cero
  // cálculos nuevos, solo un subconjunto de nodos y umbrales ya servidos.
  const { activeGroup, clearActiveGroup } = useActiveGroup();
  const groupNodeIds = useGroupNodeIds(summaries);
  const groupSummaries = useMemo(
    () => (groupNodeIds == null ? [] : summaries.filter((s) => groupNodeIds.has(s.node.node_id))),
    [summaries, groupNodeIds],
  );
  // Mismo queryKey que App.tsx/FleetView: caché compartida (M6.2, scope_to_members).
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
  const groupAttentionList = useMemo(
    () => (groupNodeIds == null || summary == null ? null : computeGroupAttention(groupSummaries, summary.thresholds)),
    [groupNodeIds, groupSummaries, summary],
  );
  // Semáforo del grupo: ver `computeGroupStatus` (groupStats.ts) para el
  // porqué no es un port exacto de `compute_status` del backend.
  const groupStatus = computeGroupStatus(groupMetrics?.criticalAlerts ?? 0, groupAttentionList?.length ?? 0);

  // Focus: sus alertas primero — prioriza, nunca oculta (§7.3)
  const isFocusAlert = (x: AlertOut) => focusId != null && x.subject_type === "node" && x.subject_id === focusId;
  const { inScope: scopedActive, outOfGroupCritical } = scopeAlertsToGroup(
    alerts.filter((a) => a.status !== "resolved"),
    groupNodeIds,
  );
  const active = scopedActive.sort((a, b) => {
    const rank = (x: AlertOut) => (x.severity === "CRITICAL" ? 0 : x.severity === "WARNING" ? 1 : 2);
    return (
      Number(isFocusAlert(b)) - Number(isFocusAlert(a)) ||
      rank(a) - rank(b) ||
      (a.fired_at < b.fired_at ? 1 : -1)
    );
  });

  const activeGwStats = groupNodeIds != null ? groupGwStats.data : stats;
  const statsById = new Map((activeGwStats?.gateways ?? []).map((g) => [g.gateway_id, g]));
  const gwRows = useMemo(
    () => scopeGatewaysToGroup(gateways, groupNodeIds, groupGwStats.data),
    [gateways, groupNodeIds, groupGwStats.data],
  );
  const gwConnected = gwRows.filter((g) => g.status === "connected").length;
  const attention =
    groupAttentionList != null
      ? [...groupAttentionList].sort((a, b) => Number(b.node_id === focusId) - Number(a.node_id === focusId))
      : [...(summary?.critical_nodes ?? [])].sort(
          (a, b) => Number(b.node_id === focusId) - Number(a.node_id === focusId),
        );
  const reasons =
    groupNodeIds == null && summary && summary.status !== "HEALTHY" ? healthReasons(summary, gateways) : [];

  const headerStatus = groupNodeIds != null ? groupStatus : summary?.status;

  // "Qué está ocurriendo" (Fase A.3): reglas sobre los mismos agregados que
  // ya pinta el bloque de arriba, generalizadas para red completa y grupo.
  const gwDownCount = gwRows.filter((g) => g.status !== "connected" && g.status !== "connecting" && g.status !== "reconnecting").length;
  const gwDegradedCount = gwRows.filter((g) => g.status === "connecting" || g.status === "reconnecting").length;
  const narrative =
    summary == null
      ? []
      : groupNodeIds != null
        ? buildSituationNarrative({
            scopeLabel: activeGroup?.name ?? "el grupo",
            nodesTotal: groupMetrics?.total ?? 0,
            attentionCount: groupAttentionList?.length ?? 0,
            gatewaysDown: gwDownCount,
            gatewaysDegraded: gwDegradedCount,
            offlinePercent:
              groupMetrics && groupMetrics.total > 0
                ? (100 * (groupMetrics.total - groupMetrics.online)) / groupMetrics.total
                : 0,
            offlinePercentWarning: summary.thresholds.offline_percent_warning,
            lowBatteryCount: (groupAttentionList ?? []).filter((n) => n.reasons.includes("low_battery")).length,
            lowBatteryThreshold: summary.thresholds.low_battery_percent,
            snrAvg: groupMetrics?.snrAvg ?? null,
            snrDegradedThreshold: summary.thresholds.snr_degraded_db,
            channelUtilizationAvg: groupMetrics?.channelUtilizationAvg ?? null,
            redundancyPercent: groupGwStats.data?.redundancy_percent ?? null,
            // Tiempo desde el ÚLTIMO contacto del grupo (no una media): con
            // grupo activo no se recalcula una media nueva por nodo, así
            // que esta señal concreta rara vez dispara en modo grupo — es
            // una limitación conocida, no un cálculo erróneo.
            avgSecondsSinceLastSeen: groupMetrics?.lastActivitySeconds ?? null,
            nodeOfflineAfterSeconds: summary.thresholds.node_offline_after_seconds,
          })
        : buildSituationNarrative({
            scopeLabel: "la red",
            nodesTotal: summary.nodes_total,
            attentionCount: attention.length,
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

  // Distribución por categorías (Fase A.4): solo tiene sentido con grupo
  // activo (ver classify.ts) — "Toda la red" nunca se clasifica.
  const categoryCounts = useMemo(
    () => (groupNodeIds != null ? groupByCategory(groupSummaries, gatewayNodeIds) : null),
    [groupNodeIds, groupSummaries, gatewayNodeIds],
  );

  // Nodos destacados (Fase A.4): mismas listas para red completa/grupo,
  // sobre el subconjunto de nodos ya escopado más arriba.
  const highlightScope = groupNodeIds != null ? groupSummaries : summaries;
  const staleAfterSeconds = summary?.thresholds.node_offline_after_seconds ?? 900;
  const highlights = useMemo(
    () => ({
      active: mostActive(highlightScope),
      noTraffic: noTraffic(highlightScope, staleAfterSeconds),
      lowBattery: lowestBattery(highlightScope),
      offline: offlineHighlights(highlightScope),
      observed: mostObserved(highlightScope),
    }),
    [highlightScope, staleAfterSeconds],
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", overflowY: "auto", height: "100%" }}>
      {/* ① Semáforo — de la red, o del grupo activo (§4.1). Con estado
          ≠HEALTHY los motivos aparecen YA expandidos: 0 clics. */}
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
            📁 GRUPO: {activeGroup.name.toUpperCase()}
          </div>
        )}
        <div style={{ display: "flex", alignItems: "baseline", gap: "0.5rem" }}>
          <span style={{ color: healthColor(headerStatus), fontWeight: 700, fontSize: 14, letterSpacing: "0.05em" }}>
            {groupNodeIds != null ? activeGroup?.name.toUpperCase() : "RED"} {headerStatus ? HEALTH_LABEL[headerStatus] : "…"}
          </span>
        </div>
        <div style={{ color: t.textDim, fontSize: 12, fontFamily: t.fontMono, fontVariantNumeric: "tabular-nums" }}>
          {groupMetrics != null
            ? `${groupMetrics.online}/${groupMetrics.total} online · ${attention.length} en atención`
            : summary
              ? `${summary.nodes_online}/${summary.nodes_total} online · ${attention.length} en atención`
              : "cargando…"}
        </div>
        {groupMetrics != null && (
          <div style={{ color: t.textDim, fontSize: 11.5, marginTop: 3, fontFamily: t.fontMono }}>
            {groupMetrics.batteryAvg != null && <>🔋 {groupMetrics.batteryAvg.toFixed(0)}% med</>}
            {groupMetrics.snrAvg != null && <> · 📶 {groupMetrics.snrAvg.toFixed(1)} dB</>}
            {groupMetrics.channelUtilizationAvg != null && <> · 📡 {groupMetrics.channelUtilizationAvg.toFixed(0)}% canal</>}
            {activeGwStats != null && activeGwStats.nodes_observed > 0 && (
              <> · 🔁 {activeGwStats.redundancy_percent}% redundancia</>
            )}
          </div>
        )}
        {groupMetrics == null && summary != null && (
          <div style={{ color: t.textDim, fontSize: 11.5, marginTop: 3, fontFamily: t.fontMono }}>
            {summary.avg_battery_percent != null && <>🔋 {summary.avg_battery_percent.toFixed(0)}% med</>}
            {summary.avg_snr != null && <> · 📶 {summary.avg_snr.toFixed(1)} dB</>}
            {summary.avg_rssi != null && <> · 📻 {summary.avg_rssi.toFixed(0)} dBm</>}
            {summary.avg_channel_utilization != null && <> · 📡 {summary.avg_channel_utilization.toFixed(0)}% canal</>}
            {stats != null && stats.nodes_observed > 0 && <> · 🔁 {stats.redundancy_percent}% redundancia</>}
          </div>
        )}
        {reasons.map((r) => (
          <div key={r} style={{ color: t.textDim, fontSize: 12, marginTop: 2 }}>
            › {r}
          </div>
        ))}
      </section>

      {/* ②a "Qué está ocurriendo" (Fase A.3): interpretación por reglas
          simples de los mismos agregados de arriba. */}
      <BlockAccordion id="situation" title="Qué está ocurriendo" icon="›">
        {narrative.length === 0 ? (
          <p style={{ color: t.textFaint, fontSize: 12, margin: 0 }}>Cargando…</p>
        ) : (
          narrative.map((line) => (
            <div key={line} style={{ color: t.text, fontSize: 12.5, padding: "0.15rem 0" }}>
              › {line}
            </div>
          ))
        )}
      </BlockAccordion>

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
          const color = alertSeverityColor(a.severity);
          return (
            <div key={a.id} style={{ ...rowStyle, alignItems: "flex-start" }}>
              <span style={{ color, fontSize: 10, lineHeight: "18px" }}>●</span>
              <span style={{ flex: 1, minWidth: 0 }}>
                {isFocusAlert(a) && <span style={{ color: t.accent }}>◎ </span>}
                <span style={{ color: t.text }}>{a.message}</span>{" "}
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
          <div key={n.node_id} style={{ ...rowStyle, background: n.node_id === focusId ? t.accentTint : undefined }}>
            <span title={n.reasons.join(", ")}>{n.reasons.map((r) => REASON_ICON[r]).join("")}</span>
            <span style={{ color: t.text, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {n.node_id === focusId && <span style={{ color: t.accent }}>◎ </span>}
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

      {/* ⑤ Distribución por categorías (Fase A.4): solo con grupo activo, ver
          classify.ts — "Toda la red" nunca se clasifica. */}
      {categoryCounts != null && (
        <BlockAccordion id="categories" title="Distribución por categorías" icon="▦">
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
            {CATEGORY_DEFS.map((def) => {
              const list = categoryCounts.get(def.id) ?? [];
              if (list.length === 0) return null;
              return (
                <button
                  key={def.id}
                  className="chip"
                  style={{ cursor: "pointer", fontSize: 11.5 }}
                  onClick={() => onGoTo("nodes")}
                >
                  {def.icon} {def.label} · {list.length}
                </button>
              );
            })}
          </div>
        </BlockAccordion>
      )}

      {/* ⑥ Nodos destacados (Fase A.4) */}
      <BlockAccordion id="hl-active" title="Más activos" icon="⚡" count={highlights.active.length} emptyLabel="Sin datos.">
        {highlights.active.map((n) => (
          <HighlightRow key={n.node_id} n={n} focusId={focusId} onOpenNode={onOpenNode} />
        ))}
      </BlockAccordion>
      <BlockAccordion id="hl-notraffic" title="Sin tráfico" icon="⛔" count={highlights.noTraffic.length} emptyLabel="Todos los nodos tienen tráfico reciente.">
        {highlights.noTraffic.map((n) => (
          <HighlightRow key={n.node_id} n={n} focusId={focusId} onOpenNode={onOpenNode} />
        ))}
      </BlockAccordion>
      <BlockAccordion id="hl-battery" title="Sin batería" icon="🪫" count={highlights.lowBattery.length} emptyLabel="Sin datos de batería baja.">
        {highlights.lowBattery.map((n) => (
          <HighlightRow key={n.node_id} n={n} focusId={focusId} onOpenNode={onOpenNode} />
        ))}
      </BlockAccordion>
      <BlockAccordion id="hl-offline" title="Offline" icon="📴" count={highlights.offline.length} emptyLabel="Ningún nodo offline.">
        {highlights.offline.map((n) => (
          <HighlightRow key={n.node_id} n={n} focusId={focusId} onOpenNode={onOpenNode} />
        ))}
      </BlockAccordion>
      <BlockAccordion id="hl-observed" title="Más utilizados" icon="🛰" count={highlights.observed.length} emptyLabel="Sin cobertura Multi-Gateway.">
        {highlights.observed.map((n) => (
          <HighlightRow key={n.node_id} n={n} focusId={focusId} onOpenNode={onOpenNode} />
        ))}
      </BlockAccordion>

      {/* ⑦ Escape discreto: el grupo manda arriba, la red completa sigue a un clic */}
      {activeGroup != null && (
        <div style={{ padding: "0.6rem 0.9rem", flexShrink: 0 }}>
          <GoTo label="Ver estado global →" onClick={clearActiveGroup} />
        </div>
      )}
    </div>
  );
}

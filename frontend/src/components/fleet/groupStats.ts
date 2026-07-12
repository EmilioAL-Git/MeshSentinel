import type {
  AlertOut,
  CriticalNodeOut,
  CriticalReason,
  GatewayOut,
  MultiGatewayStatsOut,
  NodeSummaryOut,
  ThresholdsOut,
} from "../../api/client";

/**
 * Agregados del grupo activo (fase "Flota orientada a grupos"): funciones
 * puras sobre datos ya cargados en App.tsx — nada nuevo se consulta al
 * backend salvo `/gateways/stats?group_id=` (§ ya genérica, M6.2). Cada
 * métrica que no tiene datos hoy (p. ej. ambientales: el backend solo
 * resume telemetría `kind="device"` en `last_device_telemetry`) da `null`
 * y sencillamente no se pinta — nunca se inventa un valor.
 */

function avg(values: number[]): number | null {
  if (values.length === 0) return null;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

export interface FleetGroupMetrics {
  total: number;
  online: number;
  batteryAvg: number | null;
  batteryMin: number | null;
  snrAvg: number | null;
  rssiAvg: number | null;
  channelUtilizationAvg: number | null;
  temperatureAvg: number | null;
  humidityAvg: number | null;
  pressureAvg: number | null;
  lastActivitySeconds: number | null;
  criticalAlerts: number;
}

export function computeFleetGroupMetrics(summaries: NodeSummaryOut[], alerts: AlertOut[]): FleetGroupMetrics {
  const nodeIds = new Set(summaries.map((s) => s.node.node_id));
  const online = summaries.filter((s) => s.node.online).length;

  const batteryLevels = summaries
    .map((s) => s.last_device_telemetry?.battery_level)
    .filter((b): b is number => b != null && b <= 100);
  const snrValues = summaries.map((s) => s.node.snr).filter((v): v is number => v != null);
  const rssiValues = summaries.map((s) => s.node.rssi).filter((v): v is number => v != null);
  const channelUtilizationValues = summaries
    .map((s) => s.last_device_telemetry?.channel_utilization)
    .filter((v): v is number => v != null);
  const temperatures = summaries
    .map((s) => s.last_device_telemetry?.temperature_c)
    .filter((v): v is number => v != null);
  const humidities = summaries
    .map((s) => s.last_device_telemetry?.relative_humidity)
    .filter((v): v is number => v != null);
  const pressures = summaries
    .map((s) => s.last_device_telemetry?.barometric_pressure_hpa)
    .filter((v): v is number => v != null);

  const lastSeenTimes = summaries
    .map((s) => s.node.last_seen_at)
    .filter((v): v is string => v != null)
    .map((iso) => new Date(iso).getTime());
  const mostRecent = lastSeenTimes.length > 0 ? Math.max(...lastSeenTimes) : null;

  const criticalAlerts = alerts.filter(
    (a) => a.status !== "resolved" && a.severity === "CRITICAL" && a.subject_type === "node" && nodeIds.has(a.subject_id),
  ).length;

  return {
    total: summaries.length,
    online,
    batteryAvg: avg(batteryLevels),
    batteryMin: batteryLevels.length > 0 ? Math.min(...batteryLevels) : null,
    snrAvg: avg(snrValues),
    rssiAvg: avg(rssiValues),
    channelUtilizationAvg: avg(channelUtilizationValues),
    temperatureAvg: avg(temperatures),
    humidityAvg: avg(humidities),
    pressureAvg: avg(pressures),
    lastActivitySeconds: mostRecent != null ? Math.max(0, (Date.now() - mostRecent) / 1000) : null,
    criticalAlerts,
  };
}

/**
 * "Atención" del grupo activo (StatusPanel del Centro): mismo criterio
 * EXACTO que `_critical_nodes` en `application/dashboard.py` — reutiliza los
 * umbrales ya configurados (`ThresholdsOut`, servidos por `/dashboard/summary`,
 * sin escopar) aplicados aquí solo a los nodos del grupo. No es un cálculo
 * nuevo: es el mismo, con un subconjunto — evita escopar el propio endpoint
 * de Dashboard (cambio de API mayor, fuera de alcance de esta fase).
 */
export function computeGroupAttention(summaries: NodeSummaryOut[], thresholds: ThresholdsOut): CriticalNodeOut[] {
  const result: CriticalNodeOut[] = [];
  for (const s of summaries) {
    const { node, last_device_telemetry: tel } = s;
    const reasons: CriticalReason[] = [];
    const battery = tel?.battery_level ?? null;
    if (battery != null && battery < thresholds.low_battery_percent) reasons.push("low_battery");
    if (node.last_seen_at != null) {
      const inactiveS = (Date.now() - new Date(node.last_seen_at).getTime()) / 1000;
      if (inactiveS > thresholds.offline_minutes_warning * 60) reasons.push("inactive");
    }
    if (node.snr != null && node.snr < thresholds.snr_degraded_db) reasons.push("degraded_snr");
    if (reasons.length > 0) {
      result.push({
        node_id: node.node_id,
        short_name: node.short_name,
        long_name: node.long_name,
        reasons,
        battery_level: battery,
        snr: node.snr,
        last_seen_at: node.last_seen_at,
        online: node.online,
      });
    }
  }
  result.sort((a, b) => b.reasons.length - a.reasons.length || (a.battery_level ?? 999) - (b.battery_level ?? 999));
  return result;
}

/**
 * Semáforo del grupo activo (StatusPanel, HUD, StatusBar — fase de cierre de
 * grupos): señal ligera derivada de `computeFleetGroupMetrics`/
 * `computeGroupAttention`, NO un port exacto de `compute_status` (backend,
 * `application/dashboard.py`) — escopar ese cálculo completo exigiría
 * escopar `/dashboard/summary` (cambio de API mayor, fuera de alcance).
 * Documentado aquí en un único sitio para que las tres superficies usen
 * exactamente el mismo criterio, nunca tres aproximaciones distintas.
 */
export function computeGroupStatus(
  criticalAlerts: number,
  attentionCount: number,
): "HEALTHY" | "WARNING" | "CRITICAL" {
  if (criticalAlerts > 0) return "CRITICAL";
  if (attentionCount > 0) return "WARNING";
  return "HEALTHY";
}

/**
 * Pasarelas "del grupo": las que de verdad ven tráfico de sus nodos ahora
 * mismo (según las estadísticas Multi-Gateway ya escopadas por
 * `/gateways/stats?group_id=`) — no todas las de la red. Reutilizado por
 * StatusPanel, HUD y StatusBar para no repetir el mismo filtro tres veces.
 */
export function scopeGatewaysToGroup(
  gateways: GatewayOut[],
  groupNodeIds: Set<string> | null,
  groupGwStats: MultiGatewayStatsOut | undefined,
): GatewayOut[] {
  const enabled = gateways.filter((g) => g.enabled && g.deleted_at == null);
  if (groupNodeIds == null) return enabled;
  const statsById = new Map((groupGwStats?.gateways ?? []).map((g) => [g.gateway_id, g]));
  return enabled.filter((g) => (statsById.get(g.gateway_id)?.nodes_visible ?? 0) > 0);
}

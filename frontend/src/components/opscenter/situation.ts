/**
 * "Qué está ocurriendo" (Centro de Situación, v0.9 Fase A.3): generaliza
 * `healthReasons` (antes en StatusPanel.tsx) a más condiciones, con el
 * mismo criterio — reglas simples sobre agregados YA calculados (backend
 * `dashboard.py`/`gateway_stats.py` para la red completa, `groupStats.ts`
 * para el grupo activo), sin IA y sin recalcular nada aquí. Un umbral
 * (`CHANNEL_UTILIZATION_ELEVATED_PERCENT`) no tiene hoy una fuente
 * configurable en `Thresholds` — es una heurística fija documentada aquí;
 * si Fase D (motor de reglas) lo formaliza, esta constante se retira.
 */

const CHANNEL_UTILIZATION_ELEVATED_PERCENT = 40;
const REDUNDANCY_LOW_PERCENT = 30;

export interface SituationInputs {
  scopeLabel: string;
  nodesTotal: number;
  attentionCount: number;
  gatewaysDown: number;
  gatewaysDegraded: number;
  offlinePercent: number;
  offlinePercentWarning: number;
  lowBatteryCount: number;
  lowBatteryThreshold: number;
  snrAvg: number | null;
  snrDegradedThreshold: number;
  channelUtilizationAvg: number | null;
  redundancyPercent: number | null;
  avgSecondsSinceLastSeen: number | null;
  nodeOfflineAfterSeconds: number;
}

export function buildSituationNarrative(i: SituationInputs): string[] {
  const lines: string[] = [];

  if (i.gatewaysDown > 0) {
    lines.push(`${i.gatewaysDown} pasarela(s) sin conexión en ${i.scopeLabel}.`);
  }
  if (i.gatewaysDegraded > 0) {
    lines.push(`${i.gatewaysDegraded} pasarela(s) reconectando o degradadas.`);
  }
  if (i.nodesTotal > 0 && i.offlinePercent >= i.offlinePercentWarning) {
    lines.push(
      `${Math.round(i.offlinePercent)} % de los nodos está offline (umbral ${i.offlinePercentWarning} %).`,
    );
  }
  if (i.lowBatteryCount > 0) {
    lines.push(`${i.lowBatteryCount} nodo(s) con batería por debajo del ${i.lowBatteryThreshold} %.`);
  }
  if (i.snrAvg != null && i.snrAvg < i.snrDegradedThreshold) {
    lines.push(`SNR medio degradado (${i.snrAvg.toFixed(1)} dB, umbral ${i.snrDegradedThreshold} dB).`);
  }
  if (i.channelUtilizationAvg != null && i.channelUtilizationAvg > CHANNEL_UTILIZATION_ELEVATED_PERCENT) {
    lines.push(`Utilización de canal elevada (${i.channelUtilizationAvg.toFixed(0)} %).`);
  }
  if (i.redundancyPercent != null && i.nodesTotal > 0 && i.redundancyPercent < REDUNDANCY_LOW_PERCENT) {
    lines.push(
      `Redundancia de pasarelas baja (${Math.round(i.redundancyPercent)} %): la mayoría de los nodos depende de una sola pasarela.`,
    );
  }
  if (i.avgSecondsSinceLastSeen != null && i.avgSecondsSinceLastSeen > i.nodeOfflineAfterSeconds) {
    lines.push(
      `El tiempo medio desde el último contacto (${Math.round(i.avgSecondsSinceLastSeen / 60)} min) supera el umbral de offline.`,
    );
  }
  if (i.attentionCount > 0 && lines.length === 0) {
    lines.push(`${i.attentionCount} nodo(s) requieren atención (ver detalle abajo).`);
  }
  if (lines.length === 0) {
    lines.push(`Sin incidencias relevantes en ${i.scopeLabel}.`);
  }
  return lines;
}

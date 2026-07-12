import { activeGatewayCount, type CriticalNodeOut, type NodeSummaryOut, type ThresholdsOut } from "../../api/client";
import { computeGroupAttention } from "../fleet/groupStats";

/**
 * Paneles de "nodos destacados" del Centro de Situación (Fase A.4):
 * funciones puras sobre `summaries` ya cargados en App.tsx — cero fetch
 * nuevo, cero cálculo duplicado. "Atención" reutiliza literalmente
 * `computeGroupAttention` (mismo criterio que `critical_nodes` del
 * backend). Cada lista se corta a `limit` fuera de aquí si hace falta.
 */

export interface HighlightNode {
  node_id: string;
  short_name: string | null;
  long_name: string | null;
  metricLabel: string;
}

function toHighlight(s: NodeSummaryOut, metricLabel: string): HighlightNode {
  return {
    node_id: s.node.node_id,
    short_name: s.node.short_name,
    long_name: s.node.long_name,
    metricLabel,
  };
}

function secondsSince(iso: string | null): number | null {
  return iso == null ? null : (Date.now() - new Date(iso).getTime()) / 1000;
}

export function needsAttention(summaries: NodeSummaryOut[], thresholds: ThresholdsOut): CriticalNodeOut[] {
  return computeGroupAttention(summaries, thresholds);
}

/** Más recientemente vistos (mayor tráfico reciente). */
export function mostActive(summaries: NodeSummaryOut[], limit = 6): HighlightNode[] {
  return [...summaries]
    .filter((s) => s.node.last_seen_at != null)
    .sort((a, b) => new Date(b.node.last_seen_at!).getTime() - new Date(a.node.last_seen_at!).getTime())
    .slice(0, limit)
    .map((s) => toHighlight(s, s.node.last_seen_at ?? ""));
}

/** Sin avistamiento reciente o nunca vistos: candidatos a revisión. */
export function noTraffic(summaries: NodeSummaryOut[], staleAfterSeconds: number, limit = 6): HighlightNode[] {
  return [...summaries]
    .filter((s) => {
      const age = secondsSince(s.node.last_seen_at);
      return age == null || age > staleAfterSeconds;
    })
    .sort((a, b) => (secondsSince(b.node.last_seen_at) ?? Infinity) - (secondsSince(a.node.last_seen_at) ?? Infinity))
    .slice(0, limit)
    .map((s) => toHighlight(s, s.node.last_seen_at ? "sin tráfico reciente" : "nunca visto"));
}

/** Batería más baja primero (excluye alimentación externa, código 101). */
export function lowestBattery(summaries: NodeSummaryOut[], limit = 6): HighlightNode[] {
  return summaries
    .filter((s) => {
      const b = s.last_device_telemetry?.battery_level;
      return b != null && b <= 100;
    })
    .sort((a, b) => (a.last_device_telemetry!.battery_level ?? 0) - (b.last_device_telemetry!.battery_level ?? 0))
    .slice(0, limit)
    .map((s) => toHighlight(s, `${s.last_device_telemetry!.battery_level} %`));
}

export function offline(summaries: NodeSummaryOut[], limit = 6): HighlightNode[] {
  return summaries
    .filter((s) => !s.node.online)
    .slice(0, limit)
    .map((s) => toHighlight(s, "offline"));
}

/**
 * "Más utilizados": aproximado por cobertura Multi-Gateway (nº de
 * pasarelas que oyen al nodo ahora mismo, `activeGatewayCount`, M6.2) — no
 * hay contador de tráfico/mensajes por nodo hoy. Documentado como
 * definición explícita, no una medida de uso real de la malla.
 */
export function mostObserved(summaries: NodeSummaryOut[], limit = 6): HighlightNode[] {
  return [...summaries]
    .map((s) => ({ s, count: activeGatewayCount(s) }))
    .filter((x) => x.count > 0)
    .sort((a, b) => b.count - a.count)
    .slice(0, limit)
    .map((x) => toHighlight(x.s, `${x.count} pasarela(s)`));
}

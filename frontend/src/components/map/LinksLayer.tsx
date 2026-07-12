import { Polyline } from "react-leaflet";
import type { NodeSummaryOut } from "../../api/client";

/**
 * Capa "Enlaces" del mapa (Fase B.2, v0.9): representa los ÚNICOS enlaces
 * reales que el sistema captura hoy — nodo↔pasarela (`node_gateway_links`,
 * M6.1/M6.2), NUNCA enlaces nodo↔nodo de la malla real (eso requeriría
 * ingesta de NeighborInfo, diseñada pero no implementada — ver Fase D).
 *
 * La posición de la pasarela se aproxima con la posición del NODO LOCAL de
 * esa pasarela (`gateways.local_node_id`, ya presente en `summaries` como
 * cualquier otro nodo) — no existe (ni se inventa) una tabla de posiciones
 * de pasarela separada. Si el nodo local de una pasarela no tiene posición
 * conocida, sus enlaces simplemente no se dibujan.
 */

export interface GatewayPositionInfo {
  gateway_id: string;
  local_node_id: string | null;
}

function linkColor(active: boolean, snr: number | null): string {
  if (!active) return "var(--text-faint)";
  if (snr == null) return "var(--text-dim)";
  if (snr < -12) return "var(--crit)";
  if (snr < 0) return "var(--warn)";
  return "var(--ok)";
}

export function LinksLayer({
  summaries,
  gateways,
}: {
  summaries: NodeSummaryOut[];
  gateways: GatewayPositionInfo[];
}) {
  const gatewayPosition = new Map<string, [number, number]>();
  for (const g of gateways) {
    if (!g.local_node_id) continue;
    const local = summaries.find((s) => s.node.node_id === g.local_node_id);
    if (local?.last_position) {
      gatewayPosition.set(g.gateway_id, [local.last_position.latitude, local.last_position.longitude]);
    }
  }

  const lines: { key: string; from: [number, number]; to: [number, number]; color: string; weight: number }[] = [];
  for (const s of summaries) {
    if (!s.last_position) continue;
    const from: [number, number] = [s.last_position.latitude, s.last_position.longitude];
    for (const link of s.gateway_links) {
      const to = gatewayPosition.get(link.gateway_id);
      if (!to) continue;
      lines.push({
        key: `${s.node.node_id}-${link.gateway_id}`,
        from,
        to,
        color: linkColor(link.active, link.snr),
        // Grosor por redundancia aproximada: enlace primario más grueso.
        weight: link.primary ? 2.5 : 1.25,
      });
    }
  }

  return (
    <>
      {lines.map((l) => (
        <Polyline
          key={l.key}
          positions={[l.from, l.to]}
          pathOptions={{ color: l.color, weight: l.weight, opacity: l.weight > 2 ? 0.75 : 0.4 }}
          interactive={false}
        />
      ))}
    </>
  );
}

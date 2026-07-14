import { Circle, Polygon } from "react-leaflet";
import type { GatewayOut, NodeSummaryOut } from "../../api/client";
import { convexHull, haversineMeters } from "./geometry";

const PALETTE = ["var(--cat-blue)", "var(--cat-green)", "var(--cat-orange)", "var(--cat-violet)", "var(--cat-aqua)", "var(--cat-magenta)"];

/**
 * Capa "Cobertura" (aproximada, NO un modelo de propagación RF real):
 * por cada pasarela, la envolvente convexa de las posiciones de los nodos
 * que la tienen como enlace activo (`node_gateway_links`, ya existente).
 * Con menos de 3 nodos dibuja un círculo hasta el más lejano en vez de un
 * polígono degenerado. Puramente derivada de datos ya cargados, sin
 * endpoint nuevo — misma filosofía que el resto de capas client-side (v0.9).
 */
export function CoverageLayer({ summaries, gateways }: { summaries: NodeSummaryOut[]; gateways: GatewayOut[] }) {
  const gatewayPosition = new Map<string, [number, number]>();
  for (const g of gateways) {
    if (!g.local_node_id) continue;
    const local = summaries.find((s) => s.node.node_id === g.local_node_id);
    if (local?.last_position) gatewayPosition.set(g.gateway_id, [local.last_position.latitude, local.last_position.longitude]);
  }

  const shapes = gateways
    .map((g, i) => {
      const center = gatewayPosition.get(g.gateway_id);
      if (!center) return null;
      const points = summaries
        .filter((s) => s.last_position && s.gateway_links.some((l) => l.gateway_id === g.gateway_id && l.active))
        .map((s) => [s.last_position!.latitude, s.last_position!.longitude] as [number, number]);
      if (points.length === 0) return null;
      const color = PALETTE[i % PALETTE.length];
      if (points.length < 3) {
        const radius = Math.max(200, ...points.map((p) => haversineMeters(center, p)));
        return { kind: "circle" as const, key: g.gateway_id, center, radius, color };
      }
      return { kind: "polygon" as const, key: g.gateway_id, hull: convexHull(points), color };
    })
    .filter((s): s is NonNullable<typeof s> => s != null);

  return (
    <>
      {shapes.map((s) =>
        s.kind === "circle" ? (
          <Circle
            key={s.key}
            center={s.center}
            radius={s.radius}
            pathOptions={{ color: s.color, weight: 1, opacity: 0.4, fillColor: s.color, fillOpacity: 0.08 }}
            interactive={false}
          />
        ) : (
          <Polygon
            key={s.key}
            positions={s.hull}
            pathOptions={{ color: s.color, weight: 1, opacity: 0.4, fillColor: s.color, fillOpacity: 0.08 }}
            interactive={false}
          />
        ),
      )}
    </>
  );
}

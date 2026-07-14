import { useQuery } from "@tanstack/react-query";
import { Polyline } from "react-leaflet";
import { fetchActivityLog, type GatewayOut, type NodeSummaryOut } from "../../api/client";
import { t } from "../../tokens";

/**
 * Capa "Rutas" (traceroute): reutiliza `activity_log` (persistido desde la
 * fase de hardening) filtrando por `internal_type=TRACEROUTE_APP`, sin tabla
 * nueva (decisión del usuario: no inventar modelo). Los gateways solo
 * reciben por su API los traceroutes dirigidos a su propio nodo
 * (docs/operator-notes.md), así que el origen real es SIEMPRE el nodo local
 * de la pasarela que lo recibió y el destino es `payload.node_id` — `route`
 * son solo los saltos intermedios (payload.raw.route).
 */
export function RouteLayer({ summaries, gateways }: { summaries: NodeSummaryOut[]; gateways: GatewayOut[] }) {
  const { data: items } = useQuery({
    queryKey: ["activityLog", "traceroute"],
    queryFn: () => fetchActivityLog(30, { internalType: "TRACEROUTE_APP" }),
    refetchInterval: 20_000,
  });

  const positionOf = new Map<string, [number, number]>();
  for (const s of summaries) {
    if (s.last_position) positionOf.set(s.node.node_id, [s.last_position.latitude, s.last_position.longitude]);
  }
  const localNodeOf = new Map<string, string>();
  for (const g of gateways) {
    if (g.local_node_id) localNodeOf.set(g.gateway_id, g.local_node_id);
  }

  const now = Date.now();
  const routes = (items ?? [])
    .map((item) => {
      const gatewayId = item.gateway_id;
      const localNodeId = gatewayId ? localNodeOf.get(gatewayId) : undefined;
      const originPos = localNodeId ? positionOf.get(localNodeId) : undefined;
      const destId = item.payload.node_id as string | undefined;
      const destPos = destId ? positionOf.get(destId) : undefined;
      const raw = (item.payload.raw as { route?: string[] } | undefined) ?? undefined;
      const hopPositions = (raw?.route ?? [])
        .map((hopId) => positionOf.get(hopId))
        .filter((p): p is [number, number] => p != null);
      const points = [originPos, ...hopPositions, destPos].filter(
        (p): p is [number, number] => p != null,
      );
      if (points.length < 2) return null;
      const ageMs = now - new Date(item.timestamp).getTime();
      return { key: item.log_id, points, opacity: ageMs < 30_000 ? 0.85 : ageMs < 120_000 ? 0.5 : 0.25 };
    })
    .filter((r): r is { key: number; points: [number, number][]; opacity: number } => r != null);

  return (
    <>
      {routes.map((r) => (
        <Polyline
          key={r.key}
          positions={r.points}
          pathOptions={{ color: t.catYellow, weight: 2.5, opacity: r.opacity }}
          interactive={false}
        />
      ))}
    </>
  );
}

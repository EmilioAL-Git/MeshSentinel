import { useQuery } from "@tanstack/react-query";
import { Circle, Tooltip } from "react-leaflet";
import { fetchEstimatedPositions, type NodeSummaryOut } from "../../api/client";

/**
 * Capa "Estimadas" (ADR 0035): posición INFERIDA de nodos sin GPS — centroide
 * ponderado de los nodos que los oyen directamente, dibujada como círculo
 * discontinuo del radio de incertidumbre. Nunca se pinta para un nodo con
 * posición real (la real manda siempre), y el tooltip lo deja claro.
 */
export function EstimatedLayer({
  summaries,
  onShowDetail,
}: {
  summaries: NodeSummaryOut[];
  onShowDetail: (nodeId: string) => void;
}) {
  const { data } = useQuery({
    queryKey: ["estimated-positions"],
    queryFn: fetchEstimatedPositions,
    refetchInterval: 300_000,
  });
  const byId = new Map(summaries.map((s) => [s.node.node_id, s]));
  return (
    <>
      {(data ?? []).map((e) => {
        const s = byId.get(e.node_id);
        // sin resumen visible (filtrado por grupo/capa) o con GPS real → no se pinta
        if (!s || s.last_position) return null;
        return (
          <Circle
            key={e.node_id}
            center={[e.latitude, e.longitude]}
            radius={e.radius_m}
            pathOptions={{ color: "var(--warn)", weight: 1.2, opacity: 0.8, dashArray: "5 5", fillOpacity: 0.05 }}
            eventHandlers={{ click: () => onShowDetail(e.node_id) }}
          >
            <Tooltip sticky>
              {s.node.short_name ?? e.node_id} · posición estimada (±{(e.radius_m / 1000).toFixed(1)} km, {e.anchors}{" "}
              {e.anchors === 1 ? "ancla" : "anclas"}) — sin GPS
            </Tooltip>
          </Circle>
        );
      })}
    </>
  );
}

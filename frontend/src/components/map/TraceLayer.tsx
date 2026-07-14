import { useQuery } from "@tanstack/react-query";
import { CircleMarker, Polyline } from "react-leaflet";
import { fetchNodePositions } from "../../api/client";

/**
 * Capa "Traza" (historial GPS): reutiliza `GET /nodes/{id}/positions`
 * (append-only, ya existente desde Fase 1) para dibujar el recorrido
 * reciente de UN nodo — el que esté en Focus (§7) o, si no hay Focus,
 * el seleccionado en el Inspector. Sin nodo activo, la capa no pinta nada.
 */
export function TraceLayer({ nodeId, limit = 100 }: { nodeId: string | null; limit?: number }) {
  const { data: positions } = useQuery({
    queryKey: ["nodePositions", nodeId, "trace", limit],
    queryFn: () => fetchNodePositions(nodeId!, limit),
    enabled: !!nodeId,
    refetchInterval: 15_000,
  });

  if (!nodeId || !positions || positions.length < 2) return null;

  // La API devuelve más reciente primero; el trazo se dibuja en orden temporal.
  const points = [...positions].reverse().map((p) => [p.latitude, p.longitude] as [number, number]);

  return (
    <>
      <Polyline
        positions={points}
        pathOptions={{ color: "var(--accent)", weight: 2, opacity: 0.6, dashArray: "4 4" }}
        interactive={false}
      />
      {points.slice(0, -1).map((pt, i) => (
        <CircleMarker
          key={i}
          center={pt}
          radius={2.5}
          pathOptions={{ color: "var(--accent)", fillColor: "var(--accent)", fillOpacity: 0.5, opacity: 0.5 }}
          interactive={false}
        />
      ))}
    </>
  );
}

import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect } from "react";
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";
import { relativeTime } from "../../time";

interface MiniPos {
  latitude: number;
  longitude: number;
  received_at: string | null;
}

/** Encuadra el mapa a los puntos dados — mismo patrón que `FitOnFirstData` de MapView.tsx, a escala de un único nodo. */
function FitBounds({ points }: { points: [number, number][] }) {
  const map = useMap();
  const key = points.map((p) => p.join(",")).join("|");
  useEffect(() => {
    if (points.length === 0) return;
    if (points.length === 1) {
      map.setView(points[0], 15);
      return;
    }
    map.fitBounds(L.latLngBounds(points), { padding: [28, 28], maxZoom: 16 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return null;
}

/**
 * Mini-mapa de la pestaña Posición del Inspector: historial reciente de
 * un nodo con línea que conecta los puntos en orden cronológico y el
 * último resaltado en verde — mismo `Polyline`/tiles que la capa "Traza"
 * del mapa principal (TraceLayer.tsx), pero como `MapContainer` propio
 * (aquí no hay un mapa grande contenedor donde montarse como capa).
 */
export function PositionMiniMap({ positions, height = 220 }: { positions: MiniPos[]; height?: number }) {
  if (positions.length === 0) return null;

  // La API devuelve más reciente primero; el trazo se dibuja en orden temporal.
  const ordered = [...positions].reverse();
  const points = ordered.map((p) => [p.latitude, p.longitude] as [number, number]);
  const latest = points[points.length - 1];

  return (
    <div style={{ height, borderRadius: 6, overflow: "hidden", border: "1px solid var(--border-subtle)" }}>
      <MapContainer
        center={latest}
        zoom={14}
        preferCanvas
        zoomControl
        attributionControl={false}
        dragging
        scrollWheelZoom
        style={{ height: "100%", width: "100%", background: "var(--bg)" }}
      >
        <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        <FitBounds points={points} />
        {points.length > 1 && (
          <Polyline positions={points} pathOptions={{ color: "var(--accent)", weight: 2, opacity: 0.75 }} interactive={false} />
        )}
        {ordered.map((p, i) => {
          const isLatest = i === ordered.length - 1;
          return (
            <CircleMarker
              key={`${p.received_at ?? "sin-fecha"}-${i}`}
              center={[p.latitude, p.longitude]}
              radius={isLatest ? 6 : 3}
              pathOptions={{
                color: isLatest ? "var(--ok)" : "var(--accent)",
                fillColor: isLatest ? "var(--ok)" : "var(--accent)",
                fillOpacity: isLatest ? 0.9 : 0.55,
                opacity: isLatest ? 1 : 0.6,
                weight: isLatest ? 2 : 1,
              }}
            >
              <Tooltip direction="top" offset={[0, -4]}>
                {isLatest ? "Última posición · " : ""}
                {relativeTime(p.received_at)}
              </Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>
    </div>
  );
}

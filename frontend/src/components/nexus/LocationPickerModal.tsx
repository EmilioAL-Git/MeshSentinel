import "leaflet/dist/leaflet.css";
import { useState } from "react";
import { CircleMarker, MapContainer, TileLayer, useMapEvents } from "react-leaflet";
import { Modal } from "../shell/Modal";
import { t } from "../../tokens";

/** Interpreta «lat,lon» (con o sin espacio); null si no son coordenadas válidas. */
export function parseLatLon(text: string): [number, number] | null {
  const m = text.trim().match(/^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$/);
  if (!m) return null;
  const lat = Number(m[1]);
  const lon = Number(m[2]);
  return Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? [lat, lon] : null;
}

function ClickToPick({ onPick }: { onPick: (p: [number, number]) => void }) {
  useMapEvents({ click: (e) => onPick([e.latlng.lat, e.latlng.lng]) });
  return null;
}

/**
 * Elegir unas coordenadas pinchando en un mapa. Devuelve `lat,lon` con 6
 * decimales (≈10 cm, más que de sobra); no envía nada, solo rellena el campo.
 */
export function LocationPickerModal({
  initial, onPick, onClose,
}: {
  initial?: string;
  onPick: (latLon: string) => void;
  onClose: () => void;
}) {
  const start = initial ? parseLatLon(initial) : null;
  const [point, setPoint] = useState<[number, number] | null>(start);

  return (
    <Modal title="Elegir coordenadas en el mapa" onClose={onClose} width="min(720px, 94vw)">
      <div style={{ padding: "0.6rem 0.8rem", display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ height: "min(55vh, 420px)", borderRadius: 6, overflow: "hidden", border: `1px solid ${t.borderSubtle}` }}>
          <MapContainer
            center={start ?? [40.0, -3.7]}
            zoom={start ? 14 : 6}
            style={{ height: "100%", width: "100%", background: "var(--bg)", cursor: "crosshair" }}
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <ClickToPick onPick={setPoint} />
            {point && (
              <CircleMarker center={point} radius={8} pathOptions={{ color: "#fff", weight: 2, fillColor: "#e5484d", fillOpacity: 0.95 }} />
            )}
          </MapContainer>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span className="mono" style={{ fontSize: 12.5, color: point ? t.text : t.textFaint }}>
            {point ? `${point[0].toFixed(6)},${point[1].toFixed(6)}` : "Pincha en el mapa para marcar el punto"}
          </span>
          <span style={{ flex: 1 }} />
          <button className="btn ghost" onClick={onClose}>Cancelar</button>
          <button
            className="btn primary"
            disabled={!point}
            onClick={() => {
              if (!point) return;
              onPick(`${point[0].toFixed(6)},${point[1].toFixed(6)}`);
              onClose();
            }}
          >
            Usar estas coordenadas
          </button>
        </div>
      </div>
    </Modal>
  );
}

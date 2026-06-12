import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { memo, useEffect, useMemo, useRef } from "react";
import { MapContainer, Marker, Popup, TileLayer, useMap } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import type { NodeSummaryOut } from "../api/client";
import { styles } from "../styles";

interface Props {
  summaries: NodeSummaryOut[];
  gatewayNodeIds: Set<string>;
  onShowDetail: (nodeId: string) => void;
}

const COLOR_ONLINE = "#3fb950";
const COLOR_OFFLINE = "#8b949e";
const COLOR_GATEWAY = "#d29922";

// Los iconos se cachean: crear divIcons nuevos en cada render fuerza a Leaflet
// a recrear los elementos DOM de todos los marcadores.
const iconCache = new Map<string, L.DivIcon>();

function nodeIcon(online: boolean, isGateway: boolean): L.DivIcon {
  const key = `${online}-${isGateway}`;
  let icon = iconCache.get(key);
  if (!icon) {
    const color = isGateway ? COLOR_GATEWAY : online ? COLOR_ONLINE : COLOR_OFFLINE;
    const shape = isGateway
      ? `width:16px;height:16px;transform:rotate(45deg);border-radius:3px;`
      : `width:14px;height:14px;border-radius:50%;`;
    icon = L.divIcon({
      className: "",
      html: `<div style="${shape}background:${color};border:2px solid #0d1117;box-shadow:0 0 4px rgba(0,0,0,.6)"></div>`,
      iconSize: [18, 18],
      iconAnchor: [9, 9],
    });
    iconCache.set(key, icon);
  }
  return icon;
}

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `hace ${Math.round(seconds)}s`;
  if (seconds < 3600) return `hace ${Math.round(seconds / 60)}m`;
  return `hace ${Math.round(seconds / 3600)}h`;
}

interface NodeMarkerProps {
  summary: NodeSummaryOut;
  isGateway: boolean;
  onShowDetail: (nodeId: string) => void;
}

const NodeMarker = memo(
  function NodeMarker({ summary, isGateway, onShowDetail }: NodeMarkerProps) {
    const { node, last_position: pos, last_device_telemetry: tel } = summary;
    if (!pos) return null;
    return (
      <Marker position={[pos.latitude, pos.longitude]} icon={nodeIcon(node.online, isGateway)}>
        <Popup>
          <div style={{ minWidth: 200, fontSize: "0.85rem" }}>
            <strong>{node.short_name ?? "?"}</strong> {node.long_name ?? ""}{" "}
            {isGateway && <em>(pasarela)</em>}
            <table style={{ width: "100%", marginTop: 4 }}>
              <tbody>
                <tr><td>ID</td><td style={{ fontFamily: "monospace" }}>{node.node_id}</td></tr>
                <tr><td>Estado</td><td>{node.online ? "online" : "offline"}</td></tr>
                <tr><td>Visto</td><td>{relativeTime(node.last_seen_at)}</td></tr>
                <tr>
                  <td>Batería</td>
                  <td>
                    {tel?.battery_level != null
                      ? tel.battery_level > 100 ? "⚡ ext." : `${tel.battery_level}%`
                      : "—"}
                  </td>
                </tr>
                <tr><td>SNR</td><td>{node.snr != null ? `${node.snr} dB` : "—"}</td></tr>
                <tr>
                  <td>Coords</td>
                  <td style={{ fontFamily: "monospace" }}>
                    {pos.latitude.toFixed(5)}, {pos.longitude.toFixed(5)}
                  </td>
                </tr>
              </tbody>
            </table>
            <button
              onClick={() => onShowDetail(node.node_id)}
              style={{ marginTop: 6, cursor: "pointer", width: "100%" }}
            >
              Ver detalle del nodo →
            </button>
          </div>
        </Popup>
      </Marker>
    );
  },
  (prev, next) =>
    prev.isGateway === next.isGateway &&
    prev.onShowDetail === next.onShowDetail &&
    prev.summary.node.online === next.summary.node.online &&
    prev.summary.node.snr === next.summary.node.snr &&
    prev.summary.node.last_seen_at === next.summary.node.last_seen_at &&
    prev.summary.last_position?.latitude === next.summary.last_position?.latitude &&
    prev.summary.last_position?.longitude === next.summary.last_position?.longitude &&
    prev.summary.last_device_telemetry?.battery_level ===
      next.summary.last_device_telemetry?.battery_level,
);

/** Encuadra el mapa a los marcadores solo en la primera carga de datos. */
function FitOnFirstData({ summaries }: { summaries: NodeSummaryOut[] }) {
  const map = useMap();
  const fitted = useRef(false);
  useEffect(() => {
    if (fitted.current) return;
    const points = summaries
      .filter((s) => s.last_position)
      .map((s) => [s.last_position!.latitude, s.last_position!.longitude] as [number, number]);
    if (points.length > 0) {
      fitted.current = true;
      map.fitBounds(L.latLngBounds(points).pad(0.2));
    }
  }, [summaries, map]);
  return null;
}

export function MapView({ summaries, gatewayNodeIds, onShowDetail }: Props) {
  const withPosition = useMemo(() => summaries.filter((s) => s.last_position), [summaries]);
  const withoutPosition = summaries.length - withPosition.length;

  return (
    <div style={styles.card}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem" }}>
        <h2 style={{ margin: 0 }}>Mapa de red</h2>
        <span style={styles.dim}>
          {withPosition.length} nodos con posición
          {withoutPosition > 0 && ` · ${withoutPosition} sin posición`}
        </span>
      </div>
      <MapContainer
        center={[40.4168, -3.7038]}
        zoom={12}
        preferCanvas
        style={{ height: "70vh", borderRadius: 6 }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitOnFirstData summaries={withPosition} />
        <MarkerClusterGroup chunkedLoading maxClusterRadius={50}>
          {withPosition.map((s) => (
            <NodeMarker
              key={s.node.node_id}
              summary={s}
              isGateway={gatewayNodeIds.has(s.node.node_id)}
              onShowDetail={onShowDetail}
            />
          ))}
        </MarkerClusterGroup>
      </MapContainer>
      <div style={{ ...styles.dim, marginTop: "0.5rem", fontSize: "0.8rem" }}>
        <span style={{ color: COLOR_ONLINE }}>●</span> online&nbsp;&nbsp;
        <span style={{ color: COLOR_OFFLINE }}>●</span> offline&nbsp;&nbsp;
        <span style={{ color: COLOR_GATEWAY }}>◆</span> pasarela
      </div>
    </div>
  );
}

import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { memo, useEffect, useMemo, useRef } from "react";
import { MapContainer, Marker, TileLayer, Tooltip, useMap } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import { activeGatewayCount, type NodeSummaryOut } from "../api/client";
import { styles } from "../styles";

interface Props {
  summaries: NodeSummaryOut[];
  gatewayNodeIds: Set<string>;
  onShowDetail: (nodeId: string) => void;
  /**
   * Modo lienzo (Centro de Operaciones, v0.7 §5): sin tarjeta ni título,
   * ocupa el 100 % del contenedor y la leyenda/contadores pasan a overlays
   * translúcidos sobre el propio mapa. El modo clásico sigue sirviendo a la
   * vista Mapa a pantalla completa.
   */
  fill?: boolean;
  /** Nodo abierto en el Inspector: su marcador se resalta con anillo de acento. */
  selectedId?: string | null;
  /** Expone la instancia de Leaflet (⌖ Centrar del Inspector, flyTo). */
  onMapReady?: (map: L.Map) => void;
}

const COLOR_ONLINE = "var(--ok)";
const COLOR_OFFLINE = "var(--text-dim)";
const COLOR_GATEWAY = "var(--warn)";

// Los iconos se cachean: crear divIcons nuevos en cada render fuerza a Leaflet
// a recrear los elementos DOM de todos los marcadores.
const iconCache = new Map<string, L.DivIcon>();

function nodeIcon(online: boolean, isGateway: boolean, gatewayCount: number, selected: boolean): L.DivIcon {
  const key = `${online}-${isGateway}-${gatewayCount}-${selected}`;
  let icon = iconCache.get(key);
  if (!icon) {
    const color = isGateway ? COLOR_GATEWAY : online ? COLOR_ONLINE : COLOR_OFFLINE;
    const shape = isGateway
      ? `width:16px;height:16px;transform:rotate(45deg);border-radius:3px;`
      : `width:14px;height:14px;border-radius:50%;`;
    // Badge de redundancia (M6.2): nº de pasarelas que oyen al nodo ahora
    const badge =
      gatewayCount > 1
        ? `<div style="position:absolute;top:-7px;right:-7px;background:var(--accent);color:#fff;` +
          `border-radius:8px;font-size:9px;line-height:12px;min-width:12px;text-align:center;` +
          `padding:0 2px;border:1px solid var(--bg)">${gatewayCount}</div>`
        : "";
    // Nodo abierto en el Inspector: anillo de acento (selección = --accent, §14.2)
    const ring = selected
      ? `<div style="position:absolute;inset:-6px;border:2px solid var(--accent);border-radius:50%"></div>`
      : "";
    icon = L.divIcon({
      className: "",
      html: `<div style="position:relative">${ring}<div style="${shape}background:${color};border:2px solid var(--bg);box-shadow:0 0 4px rgba(0,0,0,.6)"></div>${badge}</div>`,
      iconSize: [18, 18],
      iconAnchor: [9, 9],
    });
    iconCache.set(key, icon);
  }
  return icon;
}

interface NodeMarkerProps {
  summary: NodeSummaryOut;
  isGateway: boolean;
  isSelected: boolean;
  onShowDetail: (nodeId: string) => void;
}

// Clic en el marcador = abrir el Inspector directamente (v0.7 §5.4).
// El popup de Leaflet desapareció: el detalle vive en el Inspector y el
// hover solo enseña un tooltip mínimo de identificación.
const NodeMarker = memo(
  function NodeMarker({ summary, isGateway, isSelected, onShowDetail }: NodeMarkerProps) {
    const { node, last_position: pos, last_device_telemetry: tel } = summary;
    if (!pos) return null;
    const activeLinks = summary.gateway_links.filter((l) => l.active);
    const battery =
      tel?.battery_level != null ? (tel.battery_level > 100 ? "⚡ ext." : `${tel.battery_level}%`) : null;
    return (
      <Marker
        position={[pos.latitude, pos.longitude]}
        icon={nodeIcon(node.online, isGateway, activeLinks.length, isSelected)}
        eventHandlers={{ click: () => onShowDetail(node.node_id) }}
      >
        <Tooltip direction="top" offset={[0, -8]} opacity={1}>
          <span style={{ fontFamily: "var(--font-ui)", fontSize: 12 }}>
            {node.is_favorite && <span style={{ color: "var(--warn)" }}>★ </span>}
            <strong>{node.short_name ?? node.node_id}</strong>
            {isGateway && " ◆"} · {node.online ? "online" : "offline"}
            {battery && ` · ${battery}`}
            {activeLinks.length > 1 && ` · 🛰${activeLinks.length}`}
          </span>
        </Tooltip>
      </Marker>
    );
  },
  (prev, next) =>
    prev.isGateway === next.isGateway &&
    prev.isSelected === next.isSelected &&
    prev.onShowDetail === next.onShowDetail &&
    prev.summary.node.online === next.summary.node.online &&
    prev.summary.node.snr === next.summary.node.snr &&
    prev.summary.node.last_seen_at === next.summary.node.last_seen_at &&
    prev.summary.node.is_favorite === next.summary.node.is_favorite &&
    prev.summary.last_position?.latitude === next.summary.last_position?.latitude &&
    prev.summary.last_position?.longitude === next.summary.last_position?.longitude &&
    prev.summary.last_device_telemetry?.battery_level ===
      next.summary.last_device_telemetry?.battery_level &&
    activeGatewayCount(prev.summary) === activeGatewayCount(next.summary) &&
    prev.summary.node.gateway_id === next.summary.node.gateway_id,
);

/**
 * El mapa nunca se desmonta al plegar/redimensionar paneles (requisito duro
 * del diseño §3.2): un ResizeObserver avisa a Leaflet del nuevo tamaño del
 * contenedor para que recalcule el viewport sin remontar.
 */
/** Expone la instancia de Leaflet al exterior (⌖ Centrar del Inspector). */
function ExposeMap({ onMapReady }: { onMapReady?: (map: L.Map) => void }) {
  const map = useMap();
  useEffect(() => {
    onMapReady?.(map);
  }, [map, onMapReady]);
  return null;
}

function AutoResize() {
  const map = useMap();
  useEffect(() => {
    const container = map.getContainer();
    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(container);
    return () => observer.disconnect();
  }, [map]);
  return null;
}

const overlayStyle = {
  position: "absolute" as const,
  zIndex: 800, // por encima de las tiles de Leaflet (400), debajo de popups (1000+)
  background: "color-mix(in srgb, var(--surface) 82%, transparent)",
  backdropFilter: "blur(6px)",
  border: "1px solid var(--border)",
  borderRadius: 6,
  padding: "0.3rem 0.6rem",
  fontSize: "0.78rem",
  color: "var(--text-dim)",
};

function Legend() {
  return (
    <>
      <span style={{ color: COLOR_ONLINE }}>●</span> online&nbsp;&nbsp;
      <span style={{ color: COLOR_OFFLINE }}>●</span> offline&nbsp;&nbsp;
      <span style={{ color: COLOR_GATEWAY }}>◆</span> pasarela&nbsp;&nbsp;
      <span style={{ background: "var(--accent)", color: "#fff", borderRadius: 8, padding: "0 4px", fontSize: "0.7rem" }}>n</span>{" "}
      oído por n pasarelas
    </>
  );
}

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

export function MapView({ summaries, gatewayNodeIds, onShowDetail, fill = false, selectedId = null, onMapReady }: Props) {
  const withPosition = useMemo(() => summaries.filter((s) => s.last_position), [summaries]);
  const withoutPosition = summaries.length - withPosition.length;

  const map = (
    <MapContainer
      center={[40.4168, -3.7038]}
      zoom={12}
      preferCanvas
      zoomControl={!fill}
      style={fill ? { height: "100%", width: "100%", background: "var(--bg)" } : { height: "70vh", borderRadius: 6 }}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <ExposeMap onMapReady={onMapReady} />
      <AutoResize />
      <FitOnFirstData summaries={withPosition} />
      <MarkerClusterGroup chunkedLoading maxClusterRadius={50}>
        {withPosition.map((s) => (
          <NodeMarker
            key={s.node.node_id}
            summary={s}
            isGateway={gatewayNodeIds.has(s.node.node_id)}
            isSelected={s.node.node_id === selectedId}
            onShowDetail={onShowDetail}
          />
        ))}
      </MarkerClusterGroup>
    </MapContainer>
  );

  if (fill) {
    // Lienzo del Centro de Operaciones: overlays en las esquinas (§5.1)
    return (
      <div style={{ position: "relative", height: "100%", width: "100%" }}>
        {map}
        <div style={{ ...overlayStyle, top: 10, left: 10 }}>
          {withPosition.length} nodos en el mapa
          {withoutPosition > 0 && ` · ${withoutPosition} sin posición`}
        </div>
        <div style={{ ...overlayStyle, bottom: 10, left: 10 }}>
          <Legend />
        </div>
      </div>
    );
  }

  return (
    <div style={styles.card}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem" }}>
        <h2 style={{ margin: 0 }}>Mapa de red</h2>
        <span style={styles.dim}>
          {withPosition.length} nodos con posición
          {withoutPosition > 0 && ` · ${withoutPosition} sin posición`}
        </span>
      </div>
      {map}
      <div style={{ ...styles.dim, marginTop: "0.5rem", fontSize: "0.8rem" }}>
        <Legend />
      </div>
    </div>
  );
}

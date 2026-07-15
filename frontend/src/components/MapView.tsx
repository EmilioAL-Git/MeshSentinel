import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { memo, useCallback, useEffect, useMemo, useRef } from "react";
import { MapContainer, Marker, TileLayer, Tooltip, useMap, useMapEvents } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import { activeGatewayCount, type GatewayOut, type NodeSummaryOut } from "../api/client";
import { classifyNode } from "./fleet/classify";
import { useUrlList, useUrlNumber, useUrlParam } from "../hooks/useUrlState";
import { LayerToggle, DEFAULT_MAP_LAYERS, type MapColorMode, type MapLayerState } from "./map/LayerToggle";
import { LinksLayer } from "./map/LinksLayer";
import { NeighborsLayer } from "./map/NeighborsLayer";
import { TraceLayer } from "./map/TraceLayer";
import { RouteLayer } from "./map/RouteLayer";
import { CoverageLayer } from "./map/CoverageLayer";
import { styles } from "../styles";

interface Props {
  summaries: NodeSummaryOut[];
  gatewayNodeIds: Set<string>;
  /** Capa "Enlaces" (Fase B.2): posiciones de pasarela se derivan de su nodo local. */
  gateways: GatewayOut[];
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
  /** Nodo en Focus (§7): anillo doble; el resto se atenúa — salvo alertas. */
  focusId?: string | null;
  /** Nodos con alerta CRITICAL activa: halo pulsante permanente (nunca se atenúan). */
  alertNodeIds?: Set<string>;
  /**
   * Grupo activo ("Grupo como contexto global"): nodos fuera de él se
   * atenúan igual que con Focus — NUNCA se ocultan (contexto espacial de
   * una malla compartida). Pasarelas y alertas CRITICAL nunca se atenúan
   * por esto. `null`/`undefined` = sin grupo activo, sin atenuación.
   */
  groupNodeIds?: Set<string> | null;
  /** Pulsos de una sola vez al llegar eventos (mapa vivo, v0.7.3). */
  pulses?: MapPulse[];
  /** Expone la instancia de Leaflet (⌖ Centrar del Inspector, flyTo). */
  onMapReady?: (map: L.Map) => void;
}

export interface MapPulse {
  key: string;
  lat: number;
  lng: number;
  /** Referencia var(--…) del color del anillo. */
  color: string;
}

const COLOR_ONLINE = "var(--ok)";
const COLOR_OFFLINE = "var(--text-dim)";
const COLOR_GATEWAY = "var(--warn)";

// Los iconos se cachean: crear divIcons nuevos en cada render fuerza a Leaflet
// a recrear los elementos DOM de todos los marcadores.
const iconCache = new Map<string, L.DivIcon>();

/**
 * Color del marcador según el modo activo (Fase B.1): "status" es el
 * comportamiento de siempre; "quality" recolorea por SNR del nodo
 * (mismos umbrales que `thresholds.snr_degraded_db`, aproximados aquí
 * porque `nodeIcon` no recibe el umbral configurado); "redundancy"
 * recolorea por nº de pasarelas activas (mismo dato que el badge 🛰N).
 */
function colorFor(colorMode: MapColorMode, online: boolean, isGateway: boolean, gatewayCount: number, snr: number | null): string {
  if (colorMode === "quality" && !isGateway) {
    if (snr == null) return COLOR_OFFLINE;
    if (snr < -12) return "var(--crit)";
    if (snr < 0) return "var(--warn)";
    return COLOR_ONLINE;
  }
  if (colorMode === "redundancy" && !isGateway) {
    if (gatewayCount <= 0) return COLOR_OFFLINE;
    if (gatewayCount === 1) return "var(--warn)";
    return COLOR_ONLINE;
  }
  return isGateway ? COLOR_GATEWAY : online ? COLOR_ONLINE : COLOR_OFFLINE;
}

function nodeIcon(
  online: boolean,
  isGateway: boolean,
  gatewayCount: number,
  selected: boolean,
  focused: boolean,
  hasAlert: boolean,
  colorMode: MapColorMode = "status",
  snr: number | null = null,
): L.DivIcon {
  const key = `${online}-${isGateway}-${gatewayCount}-${selected}-${focused}-${hasAlert}-${colorMode}-${snr}`;
  let icon = iconCache.get(key);
  if (!icon) {
    const color = colorFor(colorMode, online, isGateway, gatewayCount, snr);
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
    // Selección = anillo simple; Focus = anillo doble (§7.3). Ambos --accent.
    const ring = focused
      ? `<div style="position:absolute;inset:-6px;border:2px solid var(--accent);border-radius:50%"></div>` +
        `<div style="position:absolute;inset:-11px;border:1px solid var(--accent);border-radius:50%;opacity:.55"></div>`
      : selected
        ? `<div style="position:absolute;inset:-6px;border:2px solid var(--accent);border-radius:50%"></div>`
        : "";
    // Alerta CRITICAL: halo pulsante permanente (principio 1)
    const halo = hasAlert ? `<div class="noc-alert-halo"></div>` : "";
    icon = L.divIcon({
      className: "",
      html: `<div style="position:relative">${halo}${ring}<div style="${shape}background:${color};border:2px solid var(--bg);box-shadow:0 0 4px rgba(0,0,0,.6)"></div>${badge}</div>`,
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
  isFocused: boolean;
  hasAlert: boolean;
  /** Con Focus activo, el resto de nodos se atenúa — nunca los que tienen alerta. */
  dimmed: boolean;
  colorMode: MapColorMode;
  onShowDetail: (nodeId: string) => void;
}

// Clic en el marcador = abrir el Inspector directamente (v0.7 §5.4).
// El popup de Leaflet desapareció: el detalle vive en el Inspector y el
// hover solo enseña un tooltip mínimo de identificación.
const NodeMarker = memo(
  function NodeMarker({ summary, isGateway, isSelected, isFocused, hasAlert, dimmed, colorMode, onShowDetail }: NodeMarkerProps) {
    const { node, last_position: pos, last_device_telemetry: tel } = summary;
    if (!pos) return null;
    const activeLinks = summary.gateway_links.filter((l) => l.active);
    const battery =
      tel?.battery_level != null ? (tel.battery_level > 100 ? "⚡ ext." : `${tel.battery_level}%`) : null;
    return (
      <Marker
        position={[pos.latitude, pos.longitude]}
        icon={nodeIcon(node.online, isGateway, activeLinks.length, isSelected, isFocused, hasAlert, colorMode, node.snr)}
        opacity={dimmed ? 0.45 : 1}
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
    prev.isFocused === next.isFocused &&
    prev.hasAlert === next.hasAlert &&
    prev.dimmed === next.dimmed &&
    prev.colorMode === next.colorMode &&
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

/**
 * Capas ↔ URL (`map.layers`, ADR 0026 / docs/design/urls-compartibles.md
 * §3.2): códigos cortos y legibles en vez de los nombres `showX` internos.
 * `useUrlList` compara por igualdad de conjunto contra el default, así que
 * apagar una capa que viene activada por defecto (p.ej. "Infraestructura")
 * también queda representado — no hace falta codificar altas y bajas por
 * separado.
 */
const LAYER_CODES: { code: string; key: keyof Omit<MapLayerState, "colorMode"> }[] = [
  { code: "infra", key: "showInfra" },
  { code: "gateways", key: "showGateways" },
  { code: "users", key: "showUsers" },
  { code: "fixed", key: "showFixed" },
  { code: "favorites", key: "showFavoritesOnly" },
  { code: "links", key: "showLinks" },
  { code: "neighbors", key: "showNeighbors" },
  { code: "traces", key: "showTraces" },
  { code: "routes", key: "showRoutes" },
  { code: "coverage", key: "showCoverage" },
];
const DEFAULT_ON_CODES = LAYER_CODES.filter((c) => DEFAULT_MAP_LAYERS[c.key]).map((c) => c.code);

const DEFAULT_CENTER: [number, number] = [40.4168, -3.7038];
const DEFAULT_ZOOM = 12;

/** Reporta el viewport (centro+zoom) tras cada gesto — `moveend`/`zoomend`
 * ya son eventos "de fin de gesto", sin necesidad de debounce propio. */
function ViewportSync({ onChange }: { onChange: (lat: number, lng: number, zoom: number) => void }) {
  const map = useMapEvents({
    moveend: () => {
      const c = map.getCenter();
      onChange(c.lat, c.lng, map.getZoom());
    },
    zoomend: () => {
      const c = map.getCenter();
      onChange(c.lat, c.lng, map.getZoom());
    },
  });
  return null;
}

/** Pulsos de una sola vez (mapa vivo): marcadores no interactivos con
 * animación CSS one-shot; el ciclo de vida lo gestiona el llamante. */
function PulseLayer({ pulses }: { pulses: MapPulse[] }) {
  return (
    <>
      {pulses.map((p) => (
        <Marker
          key={p.key}
          position={[p.lat, p.lng]}
          interactive={false}
          icon={L.divIcon({
            className: "",
            html: `<div class="noc-pulse-once" style="--pulse-color:${p.color}"></div>`,
            iconSize: [26, 26],
            iconAnchor: [13, 13],
          })}
        />
      ))}
    </>
  );
}

export function MapView({
  summaries,
  gatewayNodeIds,
  gateways,
  onShowDetail,
  fill = false,
  selectedId = null,
  focusId = null,
  alertNodeIds,
  groupNodeIds = null,
  pulses,
  onMapReady,
}: Props) {
  const withPosition = useMemo(() => summaries.filter((s) => s.last_position), [summaries]);
  const withoutPosition = summaries.length - withPosition.length;

  // Capas y modo de color ↔ URL (`map.layers`, `map.color` — ADR 0026):
  // sustituye el `usePersistedState("noc.map.layers", …)` anterior, que
  // además tenía un bug de doble prefijo (`noc.noc.map.layers`, documentado
  // en el ADR) al pasar una clave que ya incluía "noc.".
  const [onCodes, setOnCodes] = useUrlList("map.layers", DEFAULT_ON_CODES, { replace: true });
  const [colorMode, setColorMode] = useUrlParam<MapColorMode>("map.color", "status", {
    replace: true,
    parse: (raw) => (raw === "quality" || raw === "redundancy" ? raw : "status"),
    serialize: (v) => v,
  });
  const layers: MapLayerState = useMemo(() => {
    const obj = {} as MapLayerState;
    for (const c of LAYER_CODES) obj[c.key] = onCodes.includes(c.code);
    obj.colorMode = colorMode;
    return obj;
  }, [onCodes, colorMode]);
  const setLayers = useCallback(
    (next: MapLayerState) => {
      setOnCodes(LAYER_CODES.filter((c) => next[c.key]).map((c) => c.code));
      setColorMode(next.colorMode);
    },
    [setOnCodes, setColorMode],
  );

  // Viewport (`map.lat`/`map.lng`/`map.z` — ADR 0026): centro/zoom vividos
  // solo se aplican al MONTAR (props no controladas de Leaflet, como ya
  // hacía `center`/`zoom` antes); tras el primer render el mapa manda y
  // `ViewportSync` escribe cada gesto de vuelta a la URL.
  const [urlLat, setUrlLat] = useUrlNumber("map.lat", null, { replace: true });
  const [urlLng, setUrlLng] = useUrlNumber("map.lng", null, { replace: true });
  const [urlZoom, setUrlZoom] = useUrlNumber("map.z", null, { replace: true });
  const hasUrlViewport = urlLat != null && urlLng != null;
  const initialCenterRef = useRef<[number, number]>(hasUrlViewport ? [urlLat!, urlLng!] : DEFAULT_CENTER);
  const initialZoomRef = useRef<number>(urlZoom ?? DEFAULT_ZOOM);
  const onViewportChange = useCallback(
    (lat: number, lng: number, zoom: number) => {
      setUrlLat(Number(lat.toFixed(5)));
      setUrlLng(Number(lng.toFixed(5)));
      setUrlZoom(Math.round(zoom));
    },
    [setUrlLat, setUrlLng, setUrlZoom],
  );

  // Capas de categoría (Fase B.1): filtran qué marcadores se dibujan,
  // reutilizando `classifyNode` (mismo criterio que Flota). "Favoritos" es
  // aditivo: añade favoritos aunque su categoría esté apagada, nunca oculta.
  const visibleByLayer = useMemo(() => {
    return withPosition.filter((s) => {
      if (layers.showFavoritesOnly && s.node.is_favorite) return true;
      const cat = classifyNode(s, gatewayNodeIds);
      if (cat === "gateway") return layers.showGateways;
      if (cat === "infra") return layers.showInfra;
      if (cat === "fixed") return layers.showFixed;
      // "user" y "unclassified" comparten el toggle "Usuarios" (catch-all,
      // ver classify.ts): nunca desaparecen silenciosamente.
      return layers.showUsers;
    });
  }, [withPosition, layers, gatewayNodeIds]);

  const map = (
    <MapContainer
      center={initialCenterRef.current}
      zoom={initialZoomRef.current}
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
      <ViewportSync onChange={onViewportChange} />
      {/* Con viewport ya en la URL, el encuadre automático no debe pelear con el enlace compartido */}
      {!hasUrlViewport && <FitOnFirstData summaries={withPosition} />}
      {layers.showLinks && (
        <LinksLayer
          summaries={visibleByLayer}
          gateways={gateways.map((g) => ({ gateway_id: g.gateway_id, local_node_id: g.local_node_id }))}
        />
      )}
      {layers.showNeighbors && <NeighborsLayer summaries={visibleByLayer} />}
      {layers.showRoutes && <RouteLayer summaries={visibleByLayer} gateways={gateways} />}
      {layers.showCoverage && <CoverageLayer summaries={visibleByLayer} gateways={gateways} />}
      {layers.showTraces && <TraceLayer nodeId={focusId ?? selectedId} />}
      <MarkerClusterGroup chunkedLoading maxClusterRadius={50}>
        {visibleByLayer.map((s) => {
          const id = s.node.node_id;
          const isGateway = gatewayNodeIds.has(id);
          const hasAlert = alertNodeIds?.has(id) ?? false;
          const focusDim = focusId != null && id !== focusId && id !== selectedId && !hasAlert;
          const groupDim =
            groupNodeIds != null &&
            !groupNodeIds.has(id) &&
            !isGateway &&
            !hasAlert &&
            id !== selectedId &&
            id !== focusId;
          return (
            <NodeMarker
              key={id}
              summary={s}
              isGateway={isGateway}
              isSelected={id === selectedId}
              isFocused={id === focusId}
              hasAlert={hasAlert}
              dimmed={focusDim || groupDim}
              colorMode={layers.colorMode}
              onShowDetail={onShowDetail}
            />
          );
        })}
      </MarkerClusterGroup>
      {pulses && pulses.length > 0 && <PulseLayer pulses={pulses} />}
    </MapContainer>
  );

  if (fill) {
    // Lienzo del Centro de Operaciones: overlays en las esquinas (§5.1)
    return (
      <div style={{ position: "relative", height: "100%", width: "100%" }}>
        {map}
        <div style={{ ...overlayStyle, top: 10, left: 10 }}>
          {visibleByLayer.length} / {withPosition.length} nodos en el mapa
          {withoutPosition > 0 && ` · ${withoutPosition} sin posición`}
        </div>
        <div style={{ ...overlayStyle, top: 10, right: 10, padding: "0.4rem" }}>
          <LayerToggle layers={layers} onChange={setLayers} />
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

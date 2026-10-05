import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import * as maplibregl from "maplibre-gl";
import type { ExpressionSpecification, GeoJSONSource, Map as MlMap } from "maplibre-gl";
// MapLibre 6 es ESM puro con el worker en un módulo aparte: Vite no lo resuelve
// solo (en dev falla con "Worker failed to load"), así que se empaqueta con
// `?worker&url` y se le indica a MapLibre dónde está.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import { fetchTrace, fetchTraces, type NodeSummaryOut, type TraceOut } from "../../api/client";
import { useActiveGroup, useGroupNodeIds } from "../../context/GroupContext";
import { useIsMobile } from "../../hooks/useMediaQuery";
import { usePersistedState } from "../../hooks/usePersistedState";
import { useUrlNumber, useUrlString } from "../../hooks/useUrlState";
import { relativeTime } from "../../time";
import {
  BASE_STYLE_URL,
  DEM,
  FALLBACK_STYLE,
  EXAGGERATIONS,
  SATELLITE_ATTRIBUTION,
  SATELLITE_TILES,
  reliefColorStops,
  TERRAIN_EXAGGERATION,
  type BaseMode,
} from "./map3dConfig";
import {
  arcPointAt,
  buildArcWindow,
  type ArcSpec,
  disc,
  distanceM,
  hopsOf,
  nodesOf,
  snrColor,
  type LngLat,
  type Ribbon,
} from "./traceGeometry";
import { analyzeLos, sampleProfile, type ProfileSample } from "./elevation";
import { NodeSearch } from "./NodeSearch";
import { ProfileChart } from "./ProfileChart";
import { DEMO_NODE_INFO, DEMO_TRACE_ID, demoTrace } from "./demoTrace";
import { t } from "../../tokens";

/**
 * Mapa 3D general (relieve, satélite, nodos) con dos herramientas encima:
 *  - Nodo y trazas: buscas un nodo y SOLO entonces aparecen sus traceroutes;
 *    la traza elegida se dibuja con pilares, arcos por SNR y un pulso que
 *    recorre la ida y la vuelta (`?m3d.node=` / `?m3d.trace=` / `?m3d.op=`).
 *  - Perfil topográfico: terreno y línea de visión entre dos nodos
 *    (`?m3d.tab=profile&m3d.a=…&m3d.b=…`).
 */

maplibregl.setWorkerUrl(workerUrl);

const HOP_SECONDS = 1.8; // duración de un salto a velocidad 1×
const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

const ROLE_COLOR = { origin: "#4c8dff", dest: "#2ea06a", hop: "#aab3c5" } as const;

function polyFeature(ring: LngLat[], props: Record<string, unknown>): GeoJSON.Feature {
  return { type: "Feature", properties: props, geometry: { type: "Polygon", coordinates: [ring] } };
}

/**
 * Tamaño de pilares y arcos EN PÍXELES de pantalla: la geometría está en metros
 * y se reconstruye al cambiar el zoom (metros por píxel), así que no se ve
 * gigante al acercarse ni diminuta al alejarse.
 */
const PX = {
  halfW: 3.2,
  pillarR: 6.5,
  pillarH: 55,
  minPeak: 16,
  peakRatio: 0.2,
  segment: 14, // largo de cada prisma del arco estático
  liveSegment: 10, // ídem en la estela del pulso
  trail: 220, // largo de la estela
  head: 12, // largo de la cabeza
};
/** Color atenuado de un prisma "apagado": mezcla con el fondo (fill-extrusion no admite alfa por feature). */
function dimmed(hex: string): string {
  const mix = (c: number, bg: number) => Math.round(c * 0.3 + bg * 0.7);
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  return `rgb(${mix(r, 17)},${mix(g, 21)},${mix(b, 29)})`;
}
const SAMPLES = 96; // muestras para saber qué parte de un salto está en pantalla
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** Metros por píxel de pantalla en el centro del mapa (teselas de 512 px). */
function metersPerPixel(map: MlMap): number {
  return (78_271.5 * Math.cos((map.getCenter().lat * Math.PI) / 180)) / 2 ** map.getZoom();
}

interface Geometry {
  ribbons: Ribbon[];
  pillars: GeoJSON.Feature[];
  halfW: number;
}

/** Zona visible (con margen) en lng/lat, para dibujar con detalle solo lo que se ve. */
interface View {
  west: number;
  east: number;
  south: number;
  north: number;
}

interface DrawnHop {
  seq: number;
  leg: 0 | 1;
  a: LngLat;
  b: LngLat;
  len: number;
  color: string;
}

/** Dónde está el pulso: qué prismas del arco (los mismos que se dibujan) se iluminan. */
interface Cursor {
  hopSeq: number;
  /** posición del pulso en el salto actual, 0..1 */
  t: number;
  /** inicio de la estela en el salto actual */
  t0: number;
  /** cola de la estela en el salto anterior (si la cabeza acaba de empezar el salto) */
  prev: { seq: number; t0: number } | null;
  headLngLat: LngLat;
}

interface Scene {
  hops: DrawnHop[];
  missing: string[];
  /** extremos de cada salto dibujado (por `seq`): el zoom de «Seguir» se ajusta a ellos */
  hopEnds: Map<number, [LngLat, LngLat]>;
  bounds: maplibregl.LngLatBounds | null;
  nodeIds: string[];
  /** pilares y arcos estáticos para un zoom (m/px) y una zona visible */
  geometry: (mpp: number, view: View | null) => Geometry;
  /** pulso en la posición `p` (en saltos, 0..nº de saltos) */
  cursor: (p: number, mpp: number) => Cursor;
}

type LegView = "both" | "ida" | "vuelta";

function buildScene(trace: TraceOut, pos: Map<string, LngLat>, legView: LegView): Scene {
  const allHops = hopsOf(trace).filter((h) => legView === "both" || h.leg === (legView === "ida" ? 0 : 1));
  const ids = nodesOf(allHops);
  const located = ids.filter((id) => pos.has(id));
  const missing = ids.filter((id) => !pos.has(id));

  const hops: DrawnHop[] = allHops
    .filter((h) => pos.has(h.from) && pos.has(h.to))
    .map((h) => ({
      seq: h.seq,
      leg: h.leg,
      a: pos.get(h.from)!,
      b: pos.get(h.to)!,
      len: Math.max(1, distanceM(pos.get(h.from)!, pos.get(h.to)!)),
      color: snrColor(h.snr),
    }));
  const hopEnds = new Map<number, [LngLat, LngLat]>(hops.map((h) => [h.seq, [h.a, h.b]]));

  const sizes = (mpp: number) => ({
    halfW: Math.max(1, mpp * PX.halfW),
    pillarH: Math.max(5, mpp * PX.pillarH),
  });
  const specOf = (h: DrawnHop, mpp: number): ArcSpec => {
    const sz = sizes(mpp);
    const back = h.leg === 1;
    // Ida y vuelta se distinguen por ESPACIO (la vuelta es un arco más bajo, por
    // un carril lateral propio proporcional al salto) y por FORMA (tubo más fino)
    return {
      a: h.a,
      b: h.b,
      pillarH: sz.pillarH,
      peak: Math.max(mpp * PX.minPeak, h.len * PX.peakRatio) * (back ? 0.45 : 1),
      halfW: sz.halfW * (back ? 0.65 : 1),
      side: (back ? 1 : -1) * Math.max(sz.halfW * 2.5, h.len * 0.03),
    };
  };

  /** Rango [t0,t1] del salto que cae dentro de la zona visible (null = ninguno). */
  const visibleRange = (h: DrawnHop, v: View): [number, number] | null => {
    let first = -1;
    let last = -1;
    for (let i = 0; i <= SAMPLES; i++) {
      const t = i / SAMPLES;
      const lng = h.a[0] + (h.b[0] - h.a[0]) * t;
      const lat = h.a[1] + (h.b[1] - h.a[1]) * t;
      if (lng >= v.west && lng <= v.east && lat >= v.south && lat <= v.north) {
        if (first < 0) first = i;
        last = i;
      }
    }
    if (first < 0) return null;
    return [Math.max(0, (first - 1) / SAMPLES), Math.min(1, (last + 1) / SAMPLES)];
  };

  const geometry = (mpp: number, view: View | null): Geometry => {
    const { halfW, pillarH } = sizes(mpp);
    const ribbons: Ribbon[] = [];
    for (const h of hops) {
      const range = view ? visibleRange(h, view) : null;
      const [t0, t1] = range ?? [0, 1];
      // Visible: prismas de largo ~constante en píxeles. Fuera de pantalla no
      // hace falta detalle, pero se dibuja (grueso) por si entra al mover la cámara.
      const steps = range ? clamp(Math.ceil((h.len * (t1 - t0)) / (mpp * PX.segment)), 3, 240) : 24;
      ribbons.push(...buildArcWindow(specOf(h, mpp), t0, t1, steps, { hop: h.seq, leg: h.leg, color: h.color }));
    }
    const pillars = located.map((id) =>
      polyFeature(disc(pos.get(id)!, Math.max(2, mpp * PX.pillarR)), {
        height: pillarH,
        color: id === trace.origin_id ? ROLE_COLOR.origin : id === trace.target_id ? ROLE_COLOR.dest : ROLE_COLOR.hop,
      }),
    );
    return { ribbons, pillars, halfW };
  };

  const cursor = (p: number, mpp: number): Cursor => {
    const n = hops.length;
    const pp = clamp(p, 0, n);
    const i = Math.min(n - 1, Math.floor(pp));
    const t = pp - i;
    const h = hops[i];
    // Estela: se mide en píxeles (no en fracción del salto) y, si la cabeza está
    // al principio de un salto, continúa por el final del anterior
    const trailM = Math.min(h.len * 0.8, mpp * PX.trail);
    const tTrail = trailM / h.len;
    let prev: Cursor["prev"] = null;
    if (t < tTrail && i > 0) {
      const ph = hops[i - 1];
      prev = { seq: ph.seq, t0: Math.max(0, 1 - (trailM - t * h.len) / ph.len) };
    }
    return {
      hopSeq: h.seq,
      t,
      t0: Math.max(0, t - tTrail),
      prev,
      headLngLat: arcPointAt(specOf(h, mpp), t).lngLat,
    };
  };

  let bounds: maplibregl.LngLatBounds | null = null;
  for (const id of located) {
    const p = pos.get(id)!;
    bounds = bounds ? bounds.extend(p) : new maplibregl.LngLatBounds(p, p);
  }
  return { hops, missing, hopEnds, bounds, nodeIds: ids, geometry, cursor };
}

/** Un extremo del perfil es un nodo (`!id`) o un punto libre `lat,lng`. */
const POINT_RE = /^-?\d+(\.\d+)?,-?\d+(\.\d+)?$/;
const isPointKey = (k: string) => POINT_RE.test(k);
const pointKey = (lat: number, lng: number) => `${lat.toFixed(5)},${lng.toFixed(5)}`;
const pointLabel = (k: string) => `Punto ${k.replace(",", ", ")}`;
function pointPos(k: string): LngLat | null {
  if (!isPointKey(k)) return null;
  const [lat, lng] = k.split(",").map(Number);
  return [lng, lat];
}
/** «39.5, -2.4» (también con espacios o ;) → clave de punto, o null si no es válida. */
function parseCoords(text: string): string | null {
  const nums = text.match(/-?\d+(?:\.\d+)?/g);
  if (!nums || nums.length !== 2) return null;
  const [lat, lng] = nums.map(Number);
  return Math.abs(lat) <= 90 && Math.abs(lng) <= 180 ? pointKey(lat, lng) : null;
}

export function Map3DView({
  summaries,
  onOpenNode,
}: {
  summaries: NodeSummaryOut[];
  onOpenNode: (id: string) => void;
}) {
  const isMobile = useIsMobile();
  const [opParam, setOpParam] = useUrlNumber("m3d.op");
  const [traceParam, setTraceParam] = useUrlNumber("m3d.trace");
  const [nodeParam, setNodeParam] = useUrlString("m3d.node");
  const [tabParam, setTabParam] = useUrlString("m3d.tab");
  const [aParam, setAParam] = useUrlString("m3d.a");
  const [bParam, setBParam] = useUrlString("m3d.b");
  // El grupo activo acota lo que se ofrece (puntos y buscador); las trazas y los
  // nodos de una selección siguen saliendo aunque estén fuera del grupo
  const { activeGroupId } = useActiveGroup();
  const groupNodeIds = useGroupNodeIds(summaries);
  const scoped = useMemo(
    () => (groupNodeIds ? summaries.filter((s) => groupNodeIds.has(s.node.node_id)) : summaries),
    [summaries, groupNodeIds],
  );
  const tab: "node" | "profile" = tabParam === "profile" ? "profile" : "node";

  // ── Datos ────────────────────────────────────────────────────────────
  // Las trazas solo se piden cuando hay un nodo elegido (o se llega con un enlace)
  const nodeTraces = useQuery({
    queryKey: ["traces", "node", nodeParam],
    queryFn: () => fetchTraces({ nodeId: nodeParam!, reached: true, limit: 40, sinceHours: 24 * 30 }),
    enabled: nodeParam != null,
    refetchInterval: 20_000,
  });
  // La traza de la operación recién terminada puede tardar un instante en
  // estar confirmada en BD (el aviso por WS sale antes del commit): se
  // reintenta unos segundos.
  const byOp = useQuery({
    queryKey: ["traces", "op", opParam],
    queryFn: () => fetchTraces({ operationId: opParam ?? undefined, limit: 1 }),
    enabled: opParam != null,
    refetchInterval: (q) => ((q.state.data?.length ?? 0) > 0 || q.state.dataUpdateCount >= 8 ? false : 1_500),
  });

  const isDemo = traceParam === DEMO_TRACE_ID;
  const byId = useQuery({
    queryKey: ["traces", "id", traceParam],
    queryFn: () => fetchTrace(traceParam!),
    enabled: traceParam != null && !isDemo,
    retry: false,
  });

  const reached = useMemo(() => nodeTraces.data ?? [], [nodeTraces.data]);
  const demo = useMemo(() => demoTrace(), []);
  // Sin nodo ni enlace no hay traza: el mapa es solo un mapa. Con un nodo se
  // dibuja su traza más reciente salvo que se elija otra.
  const trace: TraceOut | null =
    tab === "profile"
      ? null
      : ((isDemo ? demo : undefined) ??
        byOp.data?.[0] ??
        (traceParam != null ? (reached.find((x) => x.id === traceParam) ?? byId.data) : undefined) ??
        (nodeParam != null && opParam == null && traceParam == null ? reached[0] : undefined) ??
        null);
  const waitingForOp = tab === "node" && opParam != null && !byOp.data?.length && byOp.isFetching;

  // Nodos sin GPS: ubicación puesta a mano con el asistente. Es un dato local de este
  // navegador para el visor (no se envía al nodo ni al backend).
  const [manualPos, setManualPos] = usePersistedState<Record<string, LngLat>>("map3d.manualPos", {});
  const [locating, setLocating] = useState<string | null>(null);
  const locatingRef = useRef(locating);
  locatingRef.current = locating;
  const locateRef = useRef<(p: LngLat) => void>(() => {});

  const info = useMemo(() => {
    const m = new Map<string, { name: string; pos: LngLat | null; manual?: boolean }>();
    for (const s of summaries) {
      const p = s.last_position;
      m.set(s.node.node_id, {
        name: s.node.long_name || s.node.short_name || s.node.node_id,
        pos: p ? [p.longitude, p.latitude] : (manualPos[s.node.node_id] ?? null),
        manual: !p && !!manualPos[s.node.node_id],
      });
    }
    if (isDemo) for (const [id, v] of DEMO_NODE_INFO) m.set(id, v);
    return m;
  }, [summaries, isDemo, manualPos]);
  const nameOf = (id: string) => info.get(id)?.name ?? id;

  const [legView, setLegView] = useState<LegView>("both");

  // La escena solo debe reconstruirse si cambia la traza o la POSICIÓN de alguno
  // de sus nodos. `summaries` se refresca a menudo (WS, sondeos) con identidad
  // nueva: depender de él reiniciaría la animación y recentraría la cámara.
  const positionsKey = trace
    ? nodesOf(hopsOf(trace))
        .map((id) => `${id}:${info.get(id)?.pos?.join(",") ?? "-"}`)
        .join("|")
    : "";
  const traceKey = trace ? `${trace.id}:${trace.route.join(",")}:${trace.route_back.join(",")}` : "";
  const scene = useMemo(() => {
    if (!trace) return null;
    const pos = new Map<string, LngLat>();
    for (const [id, v] of info) if (v.pos) pos.set(id, v.pos);
    return buildScene(trace, pos, legView);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [traceKey, positionsKey, legView]);

  // ── Estado de la reproducción ────────────────────────────────────────
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [follow, setFollow] = useState(false);
  const [terrainOn, setTerrainOn] = useState(true);
  const [baseMode, setBaseMode] = usePersistedState<BaseMode>("map3d.base", "dark");
  const [overlayRelief, setOverlayRelief] = usePersistedState<boolean>("map3d.overlayRelief", false);
  const [refs, setRefs] = usePersistedState<boolean>("map3d.refs", true);
  const [exag, setExag] = usePersistedState<number>("map3d.exag", TERRAIN_EXAGGERATION);
  const [offline, setOffline] = useState(false);
  const [ready, setReady] = useState(false);
  const [headHop, setHeadHop] = useState(-1);
  const [progressPct, setProgressPct] = useState(0);

  const hostRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const onOpenRef = useRef(onOpenNode);
  onOpenRef.current = onOpenNode;
  const demoRef = useRef(isDemo);
  demoRef.current = isDemo;
  const progressRef = useRef(0); // en prismas (float)
  const lastIdxRef = useRef(-1);
  const hopZoomRef = useRef(new Map<number, number>());
  const geoRef = useRef<Geometry | null>(null);
  const builtZoomRef = useRef(-99);
  const builtCenterRef = useRef<LngLat>([0, 0]);
  // Objetivo de la cámara en modo «Seguir»; el bucle de animación se acerca a él
  // en cada fotograma (no con easeTo: reiniciarlo en cada prisma lo deja sin
  // avanzar cuando los fotogramas van lentos)
  const camTargetRef = useRef<{ center: LngLat; zoom: number } | null>(null);
  const sceneRef = useRef(scene);
  sceneRef.current = scene;
  const followRef = useRef(follow);
  followRef.current = follow;
  const terrainRef = useRef(terrainOn);
  terrainRef.current = terrainOn;
  const exagRef = useRef(exag);
  exagRef.current = exag;
  const baseRef = useRef(baseMode);
  baseRef.current = baseMode;
  const pickRef = useRef<(id: string) => void>(() => {});
  const pointRef = useRef<(key: string) => void>(() => {});
  const [cam, setCam] = useState({ pitch: 60, bearing: -20 });
  // Móvil: el panel lateral se pliega para dejar sitio al mapa, y los ajustes de
  // fondo y de cámara quedan tras un botón
  const [panelOpen, setPanelOpen] = useState(true);
  const [optsOpen, setOptsOpen] = useState(false);
  const [tiltOpen, setTiltOpen] = useState(false);
  const [armed, setArmed] = useState<"A" | "B" | null>(null);
  const armedRef = useRef(armed);
  armedRef.current = armed;
  const [mastA, setMastA] = usePersistedState<number>("map3d.mastA", 2);
  const [mastB, setMastB] = usePersistedState<number>("map3d.mastB", 2);
  const [freqMHz, setFreqMHz] = usePersistedState<number>("map3d.freq", 868);
  // Presupuesto de enlace (valores típicos de Meshtastic; todos editables)
  const [txDbm, setTxDbm] = usePersistedState<number>("map3d.tx", 22);
  const [gainA, setGainA] = usePersistedState<number>("map3d.gainA", 3);
  const [gainB, setGainB] = usePersistedState<number>("map3d.gainB", 3);
  const [sensDbm, setSensDbm] = usePersistedState<number>("map3d.sens", -132);
  const [samples, setSamples] = useState<ProfileSample[] | null | "loading">(null);
  const [probeD, setProbeD] = useState<number | null>(null);

  // ── Creación del mapa (una vez) ──────────────────────────────────────
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const map = new maplibregl.Map({
      container: host,
      style: BASE_STYLE_URL,
      center: [-2.5, 39.5],
      zoom: 5,
      pitch: 60,
      bearing: -20,
      maxPitch: 80,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");

    let styleOk = false;
    const install = () => {
      styleOk = true;
      if (map.getSource("dem")) return; // el estilo ya se instaló
      // Relieve + sombreado (solo si el estilo es el remoto: el de reserva no tiene red)
      if (map.getStyle().sources && Object.keys(map.getStyle().sources).length > 0) {
        // Fuentes separadas para relieve y sombreado: MapLibre lo recomienda
        // (compartir una sola degrada la calidad del terreno)
        for (const id of ["dem", "dem-shade"]) {
          map.addSource(id, {
            type: "raster-dem",
            tiles: [...DEM.tiles],
            encoding: "terrarium",
            tileSize: DEM.tileSize,
            maxzoom: DEM.maxzoom,
            ...(id === "dem" ? { attribution: DEM.attribution } : {}),
          });
        }
        map.addSource("dem-color", {
          type: "raster-dem",
          tiles: [...DEM.tiles],
          encoding: "terrarium",
          tileSize: DEM.tileSize,
          maxzoom: DEM.maxzoom,
        });
        map.addSource("sat", {
          type: "raster",
          tiles: SATELLITE_TILES,
          tileSize: 256,
          maxzoom: 13,
          attribution: SATELLITE_ATTRIBUTION,
        });
        const styleLayers = map.getStyle().layers;
        // Las capas de base (satélite, relieve de color, sombreado) se insertan
        // DEBAJO de ríos, límites, agua, carreteras, edificios y etiquetas del
        // estilo: la imagen/relieve queda de fondo y las referencias encima
        const firstSymbol = styleLayers.find((l) => l.type === "symbol")?.id;
        const under = styleLayers.find((l) => l.id === "waterway")?.id ?? firstSymbol;
        map.addLayer(
          { id: "sat", type: "raster", source: "sat", layout: { visibility: "none" } },
          under,
        );
        map.addLayer(
          {
            id: "relief",
            type: "color-relief",
            source: "dem-color",
            layout: { visibility: "none" },
            paint: {
              "color-relief-color": ["interpolate", ["linear"], ["elevation"], ...reliefColorStops()] as ExpressionSpecification,
            },
          },
          under,
        );
        map.addLayer(
          {
            id: "hillshade",
            type: "hillshade",
            source: "dem-shade",
            paint: {
              "hillshade-method": "standard",
              "hillshade-exaggeration": 0.8,
              "hillshade-shadow-color": "#000000",
              "hillshade-highlight-color": "#5b6c8f",
              "hillshade-accent-color": "#000000",
            },
          },
          under,
        );
        if (terrainRef.current) map.setTerrain({ source: "dem", exaggeration: exagRef.current });
      }
      for (const id of ["pillars", "arcs", "head-shadow", "labels"]) {
        map.addSource(id, { type: "geojson", data: EMPTY });
      }
      const extrusion = (id: string, opacity: number, color?: string | unknown[]) =>
        map.addLayer({
          id,
          type: "fill-extrusion",
          source: id,
          paint: {
            "fill-extrusion-color": (color ?? ["get", "color"]) as string,
            "fill-extrusion-height": ["get", "height"],
            "fill-extrusion-base": ["coalesce", ["get", "base"], 0],
            "fill-extrusion-opacity": opacity,
            "fill-extrusion-vertical-gradient": true,
          },
        });
      // Capa general de nodos (puntos planos sobre el terreno): es lo que hace del
      // visor un mapa y no solo un reproductor de trazas
      for (const id of ["nodes", "node-sel", "los-line", "probe"]) {
        map.addSource(id, { type: "geojson", data: EMPTY });
      }
      map.addLayer({
        id: "nodes-dots",
        type: "circle",
        source: "nodes",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 3, 10, 5, 14, 7],
          "circle-color": ["case", ["get", "online"], "#2ea06a", "#6b7385"],
          "circle-stroke-color": ["case", ["get", "manual"], "#f5b73b", "#0b0f16"],
          "circle-stroke-width": ["case", ["get", "manual"], 2.5, 1],
        },
      });
      map.addLayer({
        id: "node-sel",
        type: "circle",
        source: "node-sel",
        paint: {
          "circle-radius": 11,
          "circle-color": "rgba(0,0,0,0)",
          "circle-stroke-color": ["get", "color"],
          "circle-stroke-width": 2.5,
        },
      });
      map.on("click", (e) => {
        // Asistente de ubicación de un nodo sin GPS: el clic fija dónde está
        if (locatingRef.current) {
          locateRef.current([e.lngLat.lng, e.lngLat.lat]);
          return;
        }
        // Modo «pinchar en el mapa» del perfil topográfico: un clic en vacío fija el punto
        if (!armedRef.current) return;
        if (map.queryRenderedFeatures(e.point, { layers: ["nodes-dots"] }).length) return; // lo atiende el nodo
        pointRef.current(pointKey(e.lngLat.lat, e.lngLat.lng));
      });
      map.on("click", "nodes-dots", (e) => {
        const id = e.features?.[0]?.properties?.id;
        if (id) pickRef.current(String(id));
      });
      map.on("mouseenter", "nodes-dots", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "nodes-dots", () => (map.getCanvas().style.cursor = ""));
      extrusion("pillars", 0.88);
      // UN solo arco: la estela y la cabeza del pulso son un cambio de color
      // (expresión actualizada en cada fotograma) de estos MISMOS prismas, así
      // que coinciden siempre con el arco de fondo
      extrusion("arcs", 0.95, ["get", "dim"]);
      map.addLayer({
        id: "head-shadow",
        type: "circle",
        source: "head-shadow",
        paint: { "circle-radius": 14, "circle-color": "#ffffff", "circle-opacity": 0.25, "circle-blur": 1, "circle-pitch-alignment": "map" },
      });
      // Nombres de los nodos como TEXTO del mapa (no como cajas HTML): MapLibre
      // oculta los que se pisan según prioridad, así nunca tapan el recorrido.
      // Origen y destino se muestran siempre; los saltos ceden si no caben.
      if (map.getStyle().glyphs) {
        const common = {
          "text-font": ["Montserrat Medium"],
          "text-size": 12.5,
          "text-anchor": "bottom" as const,
          "text-offset": [0, -3.2] as [number, number],
          "text-max-width": 10,
          "text-padding": 3,
          "symbol-sort-key": ["get", "rank"] as ExpressionSpecification,
        };
        const paint = {
          "text-color": ["get", "color"] as ExpressionSpecification,
          "text-halo-color": "rgba(8, 11, 17, 0.95)",
          "text-halo-width": 2,
          "text-halo-blur": 0.4,
        };
        map.addLayer({
          id: "labels",
          type: "symbol",
          source: "labels",
          filter: ["!", ["get", "key"]],
          layout: { ...common, "text-field": ["get", "name"], "text-allow-overlap": false },
          paint,
        });
        map.addLayer({
          id: "labels-key",
          type: "symbol",
          source: "labels",
          filter: ["get", "key"],
          layout: {
            ...common,
            "text-field": ["format", ["get", "role"], { "font-scale": 0.68 }, "\n", {}, ["get", "name"], {}],
            "text-allow-overlap": true,
          },
          paint,
        });
        for (const layer of ["labels", "labels-key"]) {
          map.on("click", layer, (e) => {
            const id = e.features?.[0]?.properties?.id;
            if (id && !demoRef.current) onOpenRef.current(String(id));
          });
          map.on("mouseenter", layer, () => {
            if (!demoRef.current) map.getCanvas().style.cursor = "pointer";
          });
          map.on("mouseleave", layer, () => {
            map.getCanvas().style.cursor = "";
          });
        }
      }
      if (map.getStyle().glyphs) {
        map.addLayer({
          id: "nodes-names",
          type: "symbol",
          source: "nodes",
          minzoom: 9,
          layout: {
            "text-field": ["get", "name"],
            "text-font": ["Montserrat Medium"],
            "text-size": 11,
            "text-offset": [0, 1.1],
            "text-anchor": "top",
            "text-optional": true,
          },
          paint: { "text-color": "#cfd6e4", "text-halo-color": "rgba(8,11,17,0.95)", "text-halo-width": 1.6 },
        });
      }
      map.addLayer({
        id: "los-line",
        type: "line",
        source: "los-line",
        layout: { "line-cap": "round" },
        paint: { "line-color": ["get", "color"], "line-width": 3, "line-dasharray": [2, 1.5] },
      });
      map.addLayer({
        id: "probe",
        type: "circle",
        source: "probe",
        paint: { "circle-radius": 6, "circle-color": "#ffffff", "circle-stroke-color": "#000", "circle-stroke-width": 1.5 },
      });
      setReady(true);
    };
    map.on("style.load", install);
    // Sin internet el estilo remoto no carga: se cae a un fondo plano sin relieve
    const fallback = () => {
      if (styleOk) return;
      styleOk = true;
      setOffline(true);
      map.setStyle(FALLBACK_STYLE);
    };
    map.on("error", () => {
      if (!map.isStyleLoaded()) fallback();
    });
    const timer = window.setTimeout(() => !map.isStyleLoaded() && fallback(), 9_000);

    return () => {
      window.clearTimeout(timer);
      setReady(false);
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Una exageración guardada en una versión anterior (p. ej. 1,6×) que ya no esté
  // entre las opciones se sustituye por la de por defecto
  useEffect(() => {
    if (!(EXAGGERATIONS as readonly number[]).includes(exag)) setExag(TERRAIN_EXAGGERATION);
  }, [exag, setExag]);

  // ── Relieve activable y exageración vertical ─────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.getSource("dem")) return;
    map.setTerrain(terrainOn ? { source: "dem", exaggeration: exag } : null);
  }, [terrainOn, exag, ready]);

  // ── Mapa base: oscuro / satélite / relieve, con referencias encima ───
  // Valores originales del estilo, para restaurarlos al volver al fondo oscuro
  const origPaint = useRef(new Map<string, unknown>());
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.getLayer("sat")) return;
    const overImage = baseMode !== "dark";

    map.setLayoutProperty("sat", "visibility", baseMode === "satellite" ? "visible" : "none");
    const reliefVisible = baseMode === "relief" || overlayRelief;
    map.setLayoutProperty("relief", "visibility", reliefVisible ? "visible" : "none");
    // Relieve de color: opaco como fondo; semitransparente si se superpone a otra base
    map.setPaintProperty("relief", "color-relief-opacity", baseMode === "relief" ? 1 : 0.5);

    // El sombreado se adapta a cada fondo: fuerte en el oscuro (sin él todo
    // parece plano), suave sobre la imagen real
    const shade =
      baseMode === "dark"
        ? { e: 0.9, hi: "#7f93b8", sh: "#000000" }
        : baseMode === "satellite"
          ? { e: 0.5, hi: "#ffffff", sh: "#000000" }
          : { e: 1, hi: "#ffffff", sh: "#0a1020" };
    map.setPaintProperty("hillshade", "hillshade-exaggeration", shade.e);
    map.setPaintProperty("hillshade", "hillshade-highlight-color", shade.hi);
    map.setPaintProperty("hillshade", "hillshade-shadow-color", shade.sh);

    // Las capas de referencia del estilo oscuro (carreteras, límites, agua,
    // edificios) son casi negras: sobre una imagen o un relieve de color no se
    // verían. Se aclaran mientras haya imagen debajo y se restauran al volver.
    const setP = (id: string, prop: string, value: unknown) => {
      const key = `${id}|${prop}`;
      if (!origPaint.current.has(key)) origPaint.current.set(key, map.getPaintProperty(id, prop as "line-color"));
      map.setPaintProperty(id, prop as "line-color", (overImage ? value : origPaint.current.get(key)) as string);
    };
    for (const l of map.getStyle().layers) {
      if (l.type === "line" && /^(road|bridge|tunnel)_.*(fill|path)/.test(l.id)) {
        setP(l.id, "line-color", "#ffffff");
        setP(l.id, "line-opacity", 0.8);
      } else if (l.type === "line" && /^(road|bridge|tunnel)_.*case/.test(l.id)) {
        setP(l.id, "line-color", "#000000");
        setP(l.id, "line-opacity", 0.55);
      } else if (l.type === "line" && /^boundary_/.test(l.id)) {
        setP(l.id, "line-color", "#ffffff");
        setP(l.id, "line-opacity", 0.55);
      } else if (l.id === "water" || l.id === "water_shadow") {
        setP(l.id, "fill-opacity", 0.4);
      } else if (l.id === "building" || l.id === "building-top") {
        setP(l.id, "fill-opacity", 0.3);
      }
      // Referencias (carreteras, límites, ferrocarril y sus nombres) activables
      if (
        (l.type === "line" && /^(road|bridge|tunnel|rail|boundary)/.test(l.id)) ||
        (l.type === "symbol" && /^roadname|^housenumber/.test(l.id))
      ) {
        map.setLayoutProperty(l.id, "visibility", refs ? "visible" : "none");
      }
    }
  }, [baseMode, overlayRelief, refs, ready]);

  const applyGeometry = (map: MlMap, sc: Scene) => {
    const b = map.getBounds();
    const [dx, dy] = [(b.getEast() - b.getWest()) * 0.25, (b.getNorth() - b.getSouth()) * 0.25];
    const g = sc.geometry(metersPerPixel(map), {
      west: b.getWest() - dx,
      east: b.getEast() + dx,
      south: b.getSouth() - dy,
      north: b.getNorth() + dy,
    });
    geoRef.current = g;
    builtZoomRef.current = map.getZoom();
    builtCenterRef.current = map.getCenter().toArray() as LngLat;
    (map.getSource("pillars") as GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features: g.pillars });
    (map.getSource("arcs") as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: g.ribbons.map((r) =>
        polyFeature(r.ring, { color: r.color, dim: dimmed(r.color), hop: r.hop, t: r.t, dt: r.dt, base: r.base, height: r.height }),
      ),
    });
  };

  // ── Escena estática: pilares, arcos tenues, etiquetas, encuadre ──────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const live = (id: string) => map.getSource(id) as GeoJSONSource | undefined;
    live("head-shadow")?.setData(EMPTY);
    progressRef.current = 0;
    lastIdxRef.current = -1;
    hopZoomRef.current.clear();
    camTargetRef.current = null;
    setHeadHop(-1);
    setProgressPct(0);

    if (!trace || !scene) {
      live("pillars")?.setData(EMPTY);
      live("arcs")?.setData(EMPTY);
      live("labels")?.setData(EMPTY);
      return;
    }
    applyGeometry(map, scene);

    const labelFeatures: GeoJSON.Feature[] = [];
    scene.nodeIds.forEach((id, i) => {
      const p = info.get(id)?.pos;
      if (!p) return;
      const isOrigin = id === trace.origin_id;
      const isTarget = id === trace.target_id;
      labelFeatures.push({
        type: "Feature",
        properties: {
          id,
          name: nameOf(id),
          role: isOrigin ? "ORIGEN" : isTarget ? "DESTINO" : "",
          key: isOrigin || isTarget,
          rank: isOrigin ? 0 : isTarget ? 1 : 2 + i,
          color: isOrigin ? "#8ab4ff" : isTarget ? "#7ee2a8" : "#e6ebf2",
        },
        geometry: { type: "Point", coordinates: p },
      });
    });
    live("labels")?.setData({ type: "FeatureCollection", features: labelFeatures });
    if (scene.bounds) {
      map.fitBounds(scene.bounds, {
        padding: { top: 110, bottom: 130, left: isMobile ? 40 : 90, right: isMobile ? 40 : 90 },
        pitch: 62,
        bearing: -25,
        maxZoom: 16.5,
        duration: 1400,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene, ready]);

  // Pilares y arcos mantienen su tamaño en pantalla y se detallan solo donde se
  // ve: se reconstruyen al cambiar el zoom o al desplazarse una buena parte de
  // la pantalla (mínimo 150 ms entre reconstrucciones)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !scene) return;
    let timer = 0;
    let lastAt = 0;
    const rebuild = () => {
      timer = 0;
      lastAt = performance.now();
      applyGeometry(map, scene);
    };
    const check = () => {
      if (timer) return;
      const c = map.getCenter();
      const widthM = metersPerPixel(map) * map.getContainer().clientWidth;
      const moved = distanceM([c.lng, c.lat], builtCenterRef.current);
      if (Math.abs(map.getZoom() - builtZoomRef.current) < 0.1 && moved < widthM * 0.2) return;
      timer = window.setTimeout(rebuild, Math.max(0, 150 - (performance.now() - lastAt)));
    };
    map.on("zoom", check);
    map.on("moveend", check);
    return () => {
      map.off("zoom", check);
      map.off("moveend", check);
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene, ready]);

  // Al desactivar «Seguir» la cámara vuelve a la vista general de la traza
  const followWasOn = useRef(false);
  useEffect(() => {
    const map = mapRef.current;
    if (followWasOn.current && !follow && map && ready && scene?.bounds) {
      map.fitBounds(scene.bounds, {
        padding: { top: 110, bottom: 130, left: isMobile ? 40 : 90, right: isMobile ? 40 : 90 },
        pitch: 62,
        maxZoom: 16.5,
        duration: 1200,
      });
    }
    followWasOn.current = follow;
    if (!follow) camTargetRef.current = null;
    lastIdxRef.current = -1; // al activarlo, encuadra el salto actual sin esperar al siguiente
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [follow]);

  // ── Animación del pulso ──────────────────────────────────────────────
  // El progreso se mide en SALTOS (0..n): cada salto dura HOP_SECONDS a 1×.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !scene || scene.hops.length === 0) return;
    const total = scene.hops.length;
    const rate = speed / HOP_SECONDS; // saltos por segundo
    let raf = 0;
    let prev = performance.now();
    const src = (id: string) => map.getSource(id) as GeoJSONSource | undefined;

    // Zoom en el que el salto ocupa ~la mitad del lado corto del mapa. Se calcula
    // con la distancia (metros por píxel de MapLibre, teselas de 512 px) y NO con
    // cameraForBounds, que depende de la inclinación/posición actual de la cámara
    // y daba resultados incoherentes.
    const hopZoom = (hop: number): number => {
      const cached = hopZoomRef.current.get(hop);
      if (cached != null) return cached;
      const ends = sceneRef.current?.hopEnds.get(hop);
      let z = map.getZoom();
      if (ends) {
        const dist = Math.max(30, distanceM(ends[0], ends[1]));
        const box = map.getContainer();
        const px = Math.min(box.clientWidth, box.clientHeight * 1.3) * 0.5;
        const cosLat = Math.cos((((ends[0][1] + ends[1][1]) / 2) * Math.PI) / 180);
        z = Math.log2((78_271.5 * cosLat * px) / dist);
        z = Math.max(5.5, Math.min(16.5, z));
      }
      hopZoomRef.current.set(hop, z);
      return z;
    };

    const draw = (p: number) => {
      const s = sceneRef.current;
      if (!s) return;
      const cur = s.cursor(p, metersPerPixel(map));
      // Color de cada prisma según el pulso: cabeza blanca, estela con el color
      // del SNR y el resto atenuado
      const hop: ExpressionSpecification = ["get", "hop"];
      const tt: ExpressionSpecification = ["get", "t"];
      const inCurrent: ExpressionSpecification = ["all", ["==", hop, cur.hopSeq], [">=", tt, cur.t0], ["<=", tt, cur.t]];
      const trail: ExpressionSpecification = cur.prev
        ? ["any", inCurrent, ["all", ["==", hop, cur.prev.seq], [">=", tt, cur.prev.t0]]]
        : inCurrent;
      const head: ExpressionSpecification = ["all", ["==", hop, cur.hopSeq], ["<=", ["abs", ["-", tt, cur.t]], ["get", "dt"]]];
      map.setPaintProperty("arcs", "fill-extrusion-color", [
        "case",
        head,
        "#ffffff",
        trail,
        ["get", "color"],
        ["get", "dim"],
      ]);
      src("head-shadow")?.setData({
        type: "FeatureCollection",
        features: [{ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: cur.headLngLat } }],
      });
      setHeadHop(cur.hopSeq);
      setProgressPct((p / total) * 100);
      // «Seguir»: el centro acompaña al pulso y el zoom se ajusta al salto en
      // curso (se acerca en saltos cortos, se aleja en los largos)
      camTargetRef.current = { center: cur.headLngLat, zoom: hopZoom(cur.hopSeq) };
    };

    const frame = (now: number) => {
      const dt = Math.min(0.1, (now - prev) / 1000);
      prev = now;
      if (playing) progressRef.current = Math.min(total, progressRef.current + dt * rate);
      const q = Math.floor(progressRef.current * 24);
      if (q !== lastIdxRef.current) {
        lastIdxRef.current = q;
        draw(progressRef.current);
      }
      const target = camTargetRef.current;
      if (followRef.current && target) {
        const cur = map.getCenter();
        const kPan = 1 - Math.exp(-dt * 4);
        const kZoom = 1 - Math.exp(-dt * 2); // el zoom cambia más despacio que el desplazamiento
        map.jumpTo({
          center: [cur.lng + (target.center[0] - cur.lng) * kPan, cur.lat + (target.center[1] - cur.lat) * kPan],
          zoom: map.getZoom() + (target.zoom - map.getZoom()) * kZoom,
        });
      }
      if (playing && progressRef.current >= total) setPlaying(false);
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
    };
  }, [scene, ready, playing, speed]);

  const seek = (pct: number) => {
    if (!scene) return;
    progressRef.current = (pct / 100) * scene.hops.length;
    lastIdxRef.current = -1; // fuerza redibujado
    if (!playing) {
      // un fotograma para reflejar la posición sin reanudar
      setPlaying(true);
      window.setTimeout(() => setPlaying(false), 60);
    }
  };
  const replay = () => {
    progressRef.current = 0;
    lastIdxRef.current = -1;
    setPlaying(true);
  };

  // ── Nodos del mapa general, selección y herramientas ─────────────────
  const selectNode = (id: string | null) => {
    setOpParam(null);
    setTraceParam(null);
    setNodeParam(id);
    if (id && needsLocation(id)) startLocating(id);
  };
  const pickNode = (id: string) => {
    if (tab === "profile") {
      if (!aParam) setAParam(id);
      else if (!bParam && id !== aParam) setBParam(id);
      else {
        setAParam(id);
        setBParam(null);
      }
    } else selectNode(id);
  };
  pickRef.current = (id) => {
    if (locatingRef.current) return; // el clic ya lo atiende el asistente de ubicación
    setArmed(null);
    pickNode(id);
  };
  pointRef.current = (key) => {
    if (armedRef.current === "A") setAParam(key);
    else setBParam(key);
    setArmed(null);
  };
  useEffect(() => {
    const map = mapRef.current;
    if (map) map.getCanvas().style.cursor = armed || locating ? "crosshair" : "";
  }, [armed, locating]);
  // Puntos libres y nodos se tratan igual al dibujarlos y nombrarlos
  const posOf = (k: string | null): LngLat | null => (k ? (pointPos(k) ?? info.get(k)?.pos ?? null) : null);
  const labelOf = (k: string) => (isPointKey(k) ? pointLabel(k) : nameOf(k));

  // ── Asistente: situar en el mapa un nodo sin GPS ──────────────────────
  const needsLocation = (id: string | null) => !!id && !isDemo && !isPointKey(id) && info.has(id) && !info.get(id)!.pos;
  const startLocating = (id: string) => {
    setArmed(null);
    setLocating(id);
    // Vista cenital y al norte: sin inclinación el punto pinchado coincide con lo que se ve
    mapRef.current?.easeTo({ pitch: 0, bearing: 0, duration: 600 });
    if (isMobile) setPanelOpen(false); // que se vea el mapa para pinchar
  };
  locateRef.current = (p) => {
    const id = locatingRef.current;
    if (!id) return;
    setManualPos({ ...manualPos, [id]: p });
    setLocating(null);
    if (isMobile) setPanelOpen(true);
  };
  const clearManual = (id: string) => {
    const { [id]: _drop, ...rest } = manualPos;
    setManualPos(rest);
  };
  useEffect(() => {
    if (!locating) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setLocating(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [locating]);
  const setTab = (v: "node" | "profile") => (setArmed(null), setTabParam(v === "profile" ? "profile" : null));

  const nodeFeatures = useMemo(() => {
    const feats: GeoJSON.Feature[] = [];
    for (const s of scoped) {
      const coords: LngLat | null = s.last_position
        ? [s.last_position.longitude, s.last_position.latitude]
        : (manualPos[s.node.node_id] ?? null);
      if (!coords || s.node.is_ignored) continue;
      feats.push({
        type: "Feature",
        properties: {
          id: s.node.node_id,
          name: s.node.short_name || s.node.node_id.slice(-4),
          online: s.node.online,
          manual: !s.last_position,
        },
        geometry: { type: "Point", coordinates: coords },
      });
    }
    return feats;
  }, [scoped, manualPos]);
  const nodesSig = useMemo(
    () => nodeFeatures.map((f) => `${f.properties!.id}${f.properties!.online ? 1 : 0}${f.properties!.manual ? "m" : ""}${(f.geometry as GeoJSON.Point).coordinates}`).join("|"),
    [nodeFeatures],
  );
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource("nodes") as GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features: nodeFeatures });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodesSig, ready]);

  // Los nombres de la capa general ceden ante los de la traza dibujada
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.getLayer("nodes-names")) return;
    map.setLayoutProperty("nodes-names", "visibility", trace ? "none" : "visible");
  }, [trace, ready]);

  // Anillos de selección: nodo buscado (acento) o extremos A/B del perfil topográfico
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const ring = (id: string | null, color: string): GeoJSON.Feature[] => {
      const p = posOf(id);
      return p ? [{ type: "Feature", properties: { color }, geometry: { type: "Point", coordinates: p } }] : [];
    };
    const feats =
      tab === "profile" ? [...ring(aParam, ROLE_COLOR.origin), ...ring(bParam, ROLE_COLOR.dest)] : ring(nodeParam, "#f5b73b");
    (map.getSource("node-sel") as GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features: feats });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, nodeParam, aParam, bParam, ready, nodesSig]);

  // Encuadre inicial: el mapa abre ocupando justo los nodos que se ofrecen (los
  // del grupo activo, o toda la red). Solo si no se llega con una selección
  // (traza, nodo o perfil por enlace): ahí manda la escena. Se repite al cambiar de grupo.
  const fittedFor = useRef<string | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || nodeFeatures.length === 0) return;
    const key = String(activeGroupId ?? "all");
    if (fittedFor.current === key) return;
    fittedFor.current = key;
    if (nodeParam || traceParam != null || opParam != null || aParam || bParam) return;
    const bounds = new maplibregl.LngLatBounds();
    for (const f of nodeFeatures) bounds.extend((f.geometry as GeoJSON.Point).coordinates as LngLat);
    map.fitBounds(bounds, {
      padding: { top: 60, bottom: 60, left: isMobile ? 30 : 60, right: isMobile ? 30 : 60 },
      maxZoom: 12,
      duration: 900,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, nodesSig, activeGroupId]);

  // Al buscar un nodo la cámara va a él (si luego llegan trazas, la escena reencuadra)
  useEffect(() => {
    const map = mapRef.current;
    const p = nodeParam ? info.get(nodeParam)?.pos : null;
    if (!map || !ready || !p || tab !== "node") return;
    map.flyTo({ center: p, zoom: Math.max(map.getZoom(), 11), pitch: 60, duration: 1200 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeParam, ready, tab, nodeParam ? info.get(nodeParam)?.pos?.join(",") : ""]);

  // ── Perfil topográfico ──────────────────────────────────────────────
  const posA = posOf(aParam);
  const posB = posOf(bParam);
  const posKey = `${posA?.join(",") ?? ""}|${posB?.join(",") ?? ""}`;
  useEffect(() => {
    if (tab !== "profile" || !posA || !posB) {
      setSamples(null);
      return;
    }
    let cancelled = false;
    setSamples("loading");
    sampleProfile(posA, posB).then((r) => !cancelled && setSamples(r));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, posKey]);
  const los = useMemo(
    () => (Array.isArray(samples) ? analyzeLos(samples, { mastA, mastB, freqMHz }) : null),
    [samples, mastA, mastB, freqMHz],
  );
  const losColor = los ? (los.clear ? (los.fresnelClear ? "#2ea06a" : "#e0a030") : "#e5484d") : "#4c8dff";

  // Línea A–B (y punto de la zona del gráfico bajo el ratón) sobre el mapa
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const line: GeoJSON.Feature[] =
      tab === "profile" && posA && posB
        ? [{ type: "Feature", properties: { color: losColor }, geometry: { type: "LineString", coordinates: [posA, posB] } }]
        : [];
    (map.getSource("los-line") as GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features: line });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, posKey, losColor, ready]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const sp = Array.isArray(samples) && probeD != null ? samples.reduce((m, q) => (Math.abs(q.d - probeD) < Math.abs(m.d - probeD) ? q : m)) : null;
    (map.getSource("probe") as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: sp ? [{ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: sp.lngLat } }] : [],
    });
  }, [probeD, samples, ready]);
  // Al completar el par A/B se encuadra el trayecto
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || tab !== "profile" || !posA || !posB) return;
    // Zoom calculado por distancia (como en «Seguir»): fitBounds con inclinación y
    // relleno asimétrico grande puede devolver un zoom absurdo (mundo entero)
    const bottom = isMobile ? 300 : 280;
    const box = map.getContainer();
    const px = Math.max(80, Math.min(box.clientWidth * 0.7, (box.clientHeight - bottom - 100) * 1.4));
    const dist = Math.max(100, distanceM(posA, posB));
    const midLat = (posA[1] + posB[1]) / 2;
    const zoom = clamp(Math.log2((78_271.5 * Math.cos((midLat * Math.PI) / 180) * px) / dist), 4, 14);
    map.easeTo({
      center: [(posA[0] + posB[0]) / 2, midLat],
      zoom,
      pitch: 55,
      padding: { top: 60, bottom, left: 0, right: 0 },
      duration: 1200,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, posKey, ready]);

  // Inclinación y giro de la cámara: el panel de vista los refleja y los controla
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const sync = () =>
      setCam((c) => {
        const next = { pitch: Math.round(map.getPitch()), bearing: Math.round(map.getBearing()) };
        return next.pitch === c.pitch && next.bearing === c.bearing ? c : next;
      });
    sync();
    map.on("pitch", sync);
    map.on("rotate", sync);
    return () => {
      map.off("pitch", sync);
      map.off("rotate", sync);
    };
  }, [ready]);

  // Al plegar/desplegar el panel (móvil) o girar el teléfono cambia el tamaño del
  // contenedor: MapLibre solo reacciona al redimensionado de ventana
  useEffect(() => {
    const host = hostRef.current;
    if (!host || !ready) return;
    const ro = new ResizeObserver(() => mapRef.current?.resize());
    ro.observe(host);
    return () => ro.disconnect();
  }, [ready]);

  // El relleno inferior del encuadre del perfil no debe quedarse al salir de él
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (!(tab === "profile" && posA && posB)) map.easeTo({ padding: { top: 0, bottom: 0, left: 0, right: 0 }, duration: 0 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, posKey, ready]);

  const hops = useMemo(() => (trace ? hopsOf(trace) : []), [trace]);
  const drawable = scene?.hops.length ?? 0;
  const hasBack = hops.some((h) => h.leg === 1);
  const headLeg = hops.find((h) => h.seq === headHop)?.leg;

  // ── UI ───────────────────────────────────────────────────────────────
  return (
    <div className="ws" style={{ flexDirection: isMobile ? "column" : "row" }}>
      <aside
        className="panel"
        style={isMobile ? { maxHeight: panelOpen ? "42%" : undefined, flexShrink: 0 } : { width: 310, flexShrink: 0 }}
      >
        <div className="panel-head">
          <span className="panel-title">Mapa 3D</span>
          {isMobile && (
            <button
              className="btn"
              style={{ marginLeft: "auto" }}
              onClick={() => setPanelOpen((o) => !o)}
              aria-expanded={panelOpen}
              title={panelOpen ? "Ocultar panel para ver el mapa" : "Mostrar panel"}
            >
              {panelOpen ? "▴" : "▾"}
            </button>
          )}
        </div>
        <div style={{ display: isMobile && !panelOpen ? "none" : "block", padding: "8px 10px 0" }}>
          <span className="seg" role="group" aria-label="Herramienta" style={{ display: "flex" }}>
            <button style={{ flex: 1 }} className={tab === "node" ? "on" : undefined} onClick={() => setTab("node")}>
              Nodo y trazas
            </button>
            <button style={{ flex: 1 }} className={tab === "profile" ? "on" : undefined} onClick={() => setTab("profile")}>
              Perfil topográfico
            </button>
          </span>
        </div>
        <div
          className="ws-scroll"
          style={{ padding: 10, display: isMobile && !panelOpen ? "none" : "flex", flexDirection: "column", gap: 10 }}
        >
          {tab === "node" && (
            <>
              {nodeParam ? (
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <div style={{ flex: 1, fontSize: 13, fontWeight: 650, overflowWrap: "anywhere" }}>
                    {nameOf(nodeParam)}
                    {!info.get(nodeParam)?.pos && (
                      <div style={{ fontSize: 11, fontWeight: 400, color: "var(--warn)" }}>
                        Sin GPS: no se ve en el mapa.{" "}
                        <button className="btn" style={{ padding: "1px 6px" }} onClick={() => startLocating(nodeParam)}>
                          📍 Situar en el mapa
                        </button>
                      </div>
                    )}
                    {info.get(nodeParam)?.manual && (
                      <div style={{ fontSize: 11, fontWeight: 400, color: t.textDim }}>
                        Ubicación manual (solo en este navegador){" "}
                        <button className="btn" style={{ padding: "1px 6px" }} onClick={() => startLocating(nodeParam)}>
                          Cambiar
                        </button>{" "}
                        <button className="btn" style={{ padding: "1px 6px" }} onClick={() => clearManual(nodeParam)}>
                          Quitar
                        </button>
                      </div>
                    )}
                  </div>
                  <button className="btn" onClick={() => onOpenNode(nodeParam)} title="Abrir en el Inspector">
                    Ficha
                  </button>
                  <button className="btn" onClick={() => selectNode(null)} title="Quitar selección y volver al mapa">
                    ✕
                  </button>
                </div>
              ) : (
                <NodeSearch summaries={scoped} onPick={selectNode} />
              )}

              {nodeParam && (
                <>
                  <div style={{ fontSize: 10.5, letterSpacing: "0.08em", fontWeight: 650, color: t.textDim }}>
                    TRACEROUTES · {reached.length}
                  </div>
                  {nodeTraces.isLoading && <div className="empty">Buscando trazas…</div>}
                  {!nodeTraces.isLoading && reached.length === 0 && !trace && (
                    <div className="empty">Este nodo no tiene traceroutes con resultado en los últimos 30 días.</div>
                  )}
                  <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    {reached.map((x) => (
                      <button
                        key={x.id}
                        className="btn"
                        style={{
                          textAlign: "left",
                          border: 0,
                          padding: "4px 6px",
                          background: trace?.id === x.id ? t.surface2 : "transparent",
                        }}
                        onClick={() => {
                          setOpParam(null);
                          setTraceParam(x.id);
                        }}
                      >
                        {nameOf(x.origin_id)} → {nameOf(x.target_id)}
                        <span style={{ color: t.textDim, fontSize: 11 }}>
                          {" "}
                          · {x.route.length} salto{x.route.length === 1 ? "" : "s"} · {relativeTime(x.received_at)}
                        </span>
                      </button>
                    ))}
                  </div>
                </>
              )}

              {!nodeParam && trace && (
                <button className="btn" onClick={() => selectNode(null)}>
                  ← Volver al mapa
                </button>
              )}
              {waitingForOp && <div className="empty">Esperando a que la traza quede registrada…</div>}
              {!nodeParam && !trace && !waitingForOp && (
                <div className="empty">
                  Busca un nodo (o pulsa uno en el mapa) para ver sus traceroutes. Sin selección esto es solo un mapa.
                </div>
              )}

          {trace && (
            <>
              <div style={{ fontSize: 11.5, color: t.textDim }}>
                {isDemo
                  ? "Traza de demostración (ficticia, posiciones aproximadas)"
                  : `${trace.source === "active" ? "Traceroute activo" : "Oído en la malla"} · pasarela ${trace.gateway_id ?? "—"}`}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {hops.map((h, i) => {
                  const located = info.get(h.from)?.pos && info.get(h.to)?.pos;
                  const firstOfLeg = i === 0 || hops[i - 1].leg !== h.leg;
                  const legColor = h.leg === 0 ? t.accent : t.catViolet;
                  return (
                    <Fragment key={h.seq}>
                    {firstOfLeg && (
                      <div
                        style={{
                          marginTop: i === 0 ? 0 : 8,
                          fontSize: 10.5,
                          letterSpacing: "0.08em",
                          fontWeight: 650,
                          color: legColor,
                        }}
                      >
                        {h.leg === 0
                          ? `IDA · ${nameOf(trace.origin_id)} → ${nameOf(trace.target_id)}`
                          : `VUELTA · ${nameOf(trace.target_id)} → ${nameOf(trace.origin_id)}`}
                      </div>
                    )}
                    <div
                      style={{
                        display: "flex",
                        gap: 6,
                        alignItems: "center",
                        fontSize: 12,
                        padding: "4px 6px",
                        borderLeft: `3px solid ${snrColor(h.snr)}`,
                        background: headHop === h.seq ? t.surface2 : "transparent",
                        opacity: located ? 1 : 0.5,
                      }}
                      title={located ? undefined : "Algún extremo no tiene posición GPS: no se dibuja"}
                    >
                      <span style={{ color: legColor, width: 16 }}>{h.leg === 0 ? "→" : "←"}</span>
                      <span style={{ flex: 1, overflowWrap: "anywhere" }}>
                        {nameOf(h.from)} → {nameOf(h.to)}
                      </span>
                      <span className="mono" style={{ color: snrColor(h.snr) }}>
                        {h.snr != null ? `${h.snr} dB` : "—"}
                      </span>
                    </div>
                    </Fragment>
                  );
                })}
              </div>
              {scene && scene.missing.length > 0 && (
                <div style={{ fontSize: 11.5, color: "var(--warn)" }}>
                  Sin posición GPS (no se dibujan): {scene.missing.map(nameOf).join(", ")}
                </div>
              )}
              {scene && drawable === 0 && (
                <div className="empty">Ningún tramo tiene posición en ambos extremos: no hay nada que dibujar.</div>
              )}
            </>
          )}
              {!isDemo && (
                <button className="btn" style={{ alignSelf: "flex-start" }} onClick={() => { setNodeParam(null); setOpParam(null); setTraceParam(DEMO_TRACE_ID); }}>
                  ★ Ver traza de demostración
                </button>
              )}
              {isDemo && (
                <button className="btn" style={{ alignSelf: "flex-start" }} onClick={() => setTraceParam(null)}>
                  ← Salir de la demostración
                </button>
              )}
            </>
          )}

          {tab === "profile" && (
            <>
              <div style={{ fontSize: 11.5, color: t.textDim, lineHeight: 1.4 }}>
                Relieve entre dos puntos: ¿hay línea de visión?
              </div>
              {(
                [
                  ["A", "Desde", aParam, setAParam, bParam],
                  ["B", "Hasta", bParam, setBParam, aParam],
                ] as const
              ).map(([k, label, id, set, other]) => (
                <div key={k}>
                  <div style={{ fontSize: 10.5, letterSpacing: "0.08em", fontWeight: 650, color: k === "A" ? t.accent : t.catGreen, marginBottom: 4 }}>
                    {label.toUpperCase()} ({k})
                  </div>
                  {id ? (
                    <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      <span style={{ flex: 1, fontSize: 13, overflowWrap: "anywhere" }}>
                        {labelOf(id)}
                        {!posOf(id) && !isPointKey(id) && (
                          <>
                            <span style={{ color: "var(--warn)", fontSize: 11 }}> · sin GPS </span>
                            <button className="btn" style={{ padding: "1px 6px" }} onClick={() => startLocating(id)}>
                              📍 Situar
                            </button>
                          </>
                        )}
                        {info.get(id)?.manual && <span style={{ color: t.textDim, fontSize: 11 }}> · ubicación manual</span>}
                      </span>
                      <button className="btn" onClick={() => set(null)} title="Quitar">
                        ✕
                      </button>
                    </div>
                  ) : (
                    <NodeSearch
                      summaries={scoped}
                      exclude={other ? [other] : undefined}
                      placeholder="Buscar nodo o pulsarlo en el mapa…"
                      onPick={(n) => {
                        set(n);
                        if (needsLocation(n)) startLocating(n);
                      }}
                    />
                  )}
                  {!id && (
                    <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
                      <button
                        className={armed === k ? "btn on" : "btn"}
                        onClick={() => setArmed(armed === k ? null : k)}
                        title="Pulsa en el mapa para fijar el punto"
                      >
                        {armed === k ? "Pulsa en el mapa…" : "📍 Pinchar en el mapa"}
                      </button>
                      <input
                        className="input"
                        style={{ flex: 1, minWidth: 130 }}
                        placeholder="lat, lng (ej. 39.5, -2.4)"
                        aria-label={`Coordenadas del punto ${k}`}
                        onKeyDown={(e) => {
                          if (e.key !== "Enter") return;
                          const key = parseCoords(e.currentTarget.value);
                          if (key) set(key);
                          else e.currentTarget.style.borderColor = "var(--crit)";
                        }}
                        onChange={(e) => (e.currentTarget.style.borderColor = "")}
                      />
                    </div>
                  )}
                </div>
              ))}
              {aParam && bParam && (
                <>
                  <button
                    className="btn"
                    style={{ alignSelf: "flex-start" }}
                    onClick={() => {
                      setAParam(bParam);
                      setBParam(aParam);
                    }}
                  >
                    ⇄ Intercambiar
                  </button>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6, fontSize: 11, color: t.textDim }}>
                    <label>
                      Mástil A (m)
                      <input className="input" type="number" min={0} max={200} value={mastA} style={{ width: "100%" }}
                        onChange={(e) => setMastA(Math.max(0, Number(e.target.value) || 0))} />
                    </label>
                    <label>
                      Mástil B (m)
                      <input className="input" type="number" min={0} max={200} value={mastB} style={{ width: "100%" }}
                        onChange={(e) => setMastB(Math.max(0, Number(e.target.value) || 0))} />
                    </label>
                    <label>
                      Banda
                      <select className="input" value={freqMHz} style={{ width: "100%" }} onChange={(e) => setFreqMHz(Number(e.target.value))}>
                        {[170, 433, 868, 915, 2400].map((f) => (
                          <option key={f} value={f}>
                            {f} MHz
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, fontSize: 11, color: t.textDim }}>
                    {(
                      [
                        ["Potencia TX (dBm)", txDbm, setTxDbm, 0, 36, "Potencia con la que transmite A (típico 14–27 dBm)"],
                        ["Sensibilidad (dBm)", sensDbm, setSensDbm, -160, -90, "Señal mínima que decodifica la radio: LongFast ≈ −132, LongSlow ≈ −137"],
                        ["Ganancia ant. A (dBi)", gainA, setGainA, -5, 30, "Ganancia de la antena de A"],
                        ["Ganancia ant. B (dBi)", gainB, setGainB, -5, 30, "Ganancia de la antena de B"],
                      ] as const
                    ).map(([label, value, set, min, max, tip]) => (
                      <label key={label} title={tip}>
                        {label}
                        <input className="input" type="number" min={min} max={max} value={value} style={{ width: "100%" }}
                          onChange={(e) => set(Number(e.target.value) || 0)} />
                      </label>
                    ))}
                  </div>
                  {(!posA || !posB) && (
                    <div style={{ fontSize: 11.5, color: "var(--warn)" }}>Un extremo no tiene posición GPS: no se puede calcular.</div>
                  )}
                  {samples === "loading" && <div className="empty">Leyendo el relieve…</div>}
                  {posA && posB && samples === null && <div className="empty">No se pudo leer el relieve (¿sin conexión con el servidor de mapas?).</div>}
                  {los && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12 }}>
                      <div style={{ fontWeight: 650, color: losColor }}>
                        {los.clear
                          ? los.fresnelClear
                            ? "● Línea de visión despejada"
                            : "● Visión directa, Fresnel comprometido"
                          : "● Obstruida por el terreno"}
                      </div>
                      <div>Distancia: {los.distanceM >= 1000 ? `${(los.distanceM / 1000).toFixed(2)} km` : `${Math.round(los.distanceM)} m`}</div>
                      <div title="Pérdida en espacio libre: 20·log10(d km) + 20·log10(f MHz) + 32,44. Es el mínimo teórico sin obstáculos; el terreno, la vegetación y los edificios añaden más pérdida.">
                        <strong>FSPL: {los.fsplDb.toFixed(1)} dB</strong>{" "}
                        <span style={{ color: t.textDim }}>a {los.freqMHz} MHz (espacio libre)</span>
                      </div>
                      <div title="RSSI esperado = potencia TX + ganancia A + ganancia B − FSPL. Es el mejor caso (sin obstáculos ni cables): el real será igual o peor.">
                        <strong>RSSI esperado: {(txDbm + gainA + gainB - los.fsplDb).toFixed(0)} dBm</strong>{" "}
                        <span style={{ color: t.textDim }}>en espacio libre</span>
                      </div>
                      <div
                        style={{
                          color: txDbm + gainA + gainB - los.fsplDb - sensDbm > 10 ? t.ok : txDbm + gainA + gainB - los.fsplDb - sensDbm > 0 ? t.warn : t.crit,
                        }}
                        title="Margen = RSSI esperado − sensibilidad. Debe cubrir pérdidas por obstáculos, vegetación, cables y desvanecimiento."
                      >
                        Margen sobre sensibilidad: {(txDbm + gainA + gainB - los.fsplDb - sensDbm).toFixed(0)} dB
                        {!los.clear && " · con obstrucción será menor"}
                      </div>
                      <div>
                        Peor punto: {Math.round(los.worst.clearance)} m de holgura a{" "}
                        {(los.worst.d / 1000).toFixed(2)} km
                      </div>
                      <div>1.ª zona de Fresnel en el centro: {los.fresnelMidM.toFixed(1)} m de radio</div>
                      <div>
                        Antenas a {Math.round(los.heightA)} m / {Math.round(los.heightB)} m s. n. m.
                      </div>
                      {los.gaps > 0 && <div style={{ color: "var(--warn)" }}>Faltan datos de relieve en {los.gaps} muestras.</div>}
                    </div>
                  )}
                </>
              )}
              <div style={{ fontSize: 10.5, color: t.textFaint }}>
                La altura de cada antena se toma del relieve bajo el nodo más el mástil indicado (la altitud GPS
                suele ser imprecisa). Incluye curvatura terrestre (k = 4/3). Fresnel: 60 % de la 1.ª zona. Orientativo:
                no considera edificios ni vegetación.
              </div>
            </>
          )}
        </div>
      </aside>

      <div style={{ flex: 1, minWidth: 0, minHeight: 0, position: "relative" }}>
        <div ref={hostRef} style={{ position: "absolute", inset: 0 }} />
        <div className="m3d-base" role="group" aria-label="Mapa base">
          <span className="seg">
            {([["dark", "Oscuro"], ["satellite", "Satélite"], ["relief", "Relieve"]] as const).map(([v, label]) => (
              <button key={v} className={baseMode === v ? "on" : undefined} disabled={offline} onClick={() => setBaseMode(v)}>
                {label}
              </button>
            ))}
          </span>
          {isMobile && (
            <button className="btn m3d-chip" onClick={() => setOptsOpen((o) => !o)} aria-expanded={optsOpen} title="Más ajustes del mapa">
              {optsOpen ? "✕" : "⋯"}
            </button>
          )}
          {(!isMobile || optsOpen) && (
            <>
          <select
            className="input"
            value={exag}
            disabled={offline || !terrainOn}
            onChange={(e) => setExag(Number(e.target.value))}
            title="Exageración vertical del relieve (1× = altura real)"
            aria-label="Exageración vertical"
          >
            {EXAGGERATIONS.map((v) => (
              <option key={v} value={v}>
                {v}× alto
              </option>
            ))}
          </select>
          <label className="m3d-check m3d-chip" title="Superpone el relieve de color (según altitud) al fondo elegido">
            <input
              type="checkbox"
              checked={overlayRelief || baseMode === "relief"}
              disabled={offline || baseMode === "relief"}
              onChange={(e) => setOverlayRelief(e.target.checked)}
            />{" "}
            + Relieve color
          </label>
          <label className="m3d-check m3d-chip" title="Carreteras, límites y sus nombres sobre el fondo">
            <input type="checkbox" checked={refs} disabled={offline} onChange={(e) => setRefs(e.target.checked)} /> Referencias
          </label>
            </>
          )}
        </div>
        {isMobile && !tiltOpen && (
          <button className="btn m3d-tilt-toggle" onClick={() => setTiltOpen(true)} title="Inclinación y giro">
            ◭
          </button>
        )}
        <div className="m3d-tilt" role="group" aria-label="Vista de la cámara" style={isMobile && !tiltOpen ? { display: "none" } : undefined}>
          {isMobile && (
            <button className="btn" onClick={() => setTiltOpen(false)} aria-label="Cerrar vista de cámara">
              ✕ Cerrar
            </button>
          )}
          <label title="Inclinación de la cámara (0° = desde arriba)">
            <span>Inclinación</span>
            <input
              type="range"
              min={0}
              max={80}
              value={cam.pitch}
              onChange={(e) => mapRef.current?.setPitch(Number(e.target.value))}
            />
            <span className="mono">{cam.pitch}°</span>
          </label>
          <label title="Giro del mapa">
            <span>Giro</span>
            <input
              type="range"
              min={-180}
              max={180}
              value={cam.bearing}
              onChange={(e) => mapRef.current?.setBearing(Number(e.target.value))}
            />
            <span className="mono">{cam.bearing}°</span>
          </label>
          <div style={{ display: "flex", gap: 4 }}>
            <button className="btn" onClick={() => mapRef.current?.easeTo({ pitch: 0, bearing: 0, duration: 500 })}>
              2D
            </button>
            <button className="btn" onClick={() => mapRef.current?.easeTo({ pitch: 60, duration: 500 })}>
              3D
            </button>
            <button className="btn" onClick={() => mapRef.current?.easeTo({ pitch: 75, duration: 500 })} title="Casi a ras de suelo">
              Rasante
            </button>
            <button className="btn" onClick={() => mapRef.current?.easeTo({ bearing: 0, duration: 500 })} title="Orientar al norte">
              N
            </button>
          </div>
        </div>
        {locating && (
          <div className="m3d-wizard" role="status">
            <div>
              <strong>📍 Situar «{nameOf(locating)}»</strong>
              <div style={{ fontSize: 12, color: t.textDim }}>
                Este nodo no tiene GPS. Pulsa en el mapa dónde está (solo se guarda en este navegador).
              </div>
            </div>
            <button className="btn" onClick={() => setLocating(null)}>
              Cancelar
            </button>
          </div>
        )}
        {tab === "profile" && los && aParam && bParam && (
          <div className="m3d-controls" style={{ width: "min(900px, calc(100% - 24px))", display: "block" }}>
            <ProfileChart los={los} nameA={labelOf(aParam)} nameB={labelOf(bParam)} onProbe={setProbeD} />
          </div>
        )}
        {offline && (
          <div className="m3d-note">
            Sin conexión con el servidor de mapas: fondo plano y sin relieve (el dibujo de la traza sigue funcionando).
          </div>
        )}
        {trace && drawable > 0 && headLeg != null && (
          <div className="m3d-badge" style={{ borderColor: headLeg === 0 ? t.accent : t.catViolet, color: headLeg === 0 ? t.accent : t.catViolet }}>
            {headLeg === 0 ? "→ IDA" : "← VUELTA"}
          </div>
        )}
        {trace && drawable > 0 && (
          <div className="m3d-controls">
            <button className="btn" onClick={() => (progressRef.current >= drawable ? replay() : setPlaying((p) => !p))}>
              {playing ? "⏸" : progressRef.current >= drawable ? "↻" : "▶"}
            </button>
            <input
              type="range"
              min={0}
              max={100}
              step={0.5}
              value={progressPct}
              onChange={(e) => seek(Number(e.target.value))}
              style={{ flex: 1, minWidth: 80 }}
              aria-label="Progreso de la traza"
            />
            <select className="input" value={speed} onChange={(e) => setSpeed(Number(e.target.value))} aria-label="Velocidad">
              {[0.5, 1, 2, 4].map((v) => (
                <option key={v} value={v}>
                  {v}×
                </option>
              ))}
            </select>
            {hasBack && (
              <span className="seg" role="group" aria-label="Sentido">
                {([["both", "Ambas"], ["ida", "Ida"], ["vuelta", "Vuelta"]] as const).map(([v, label]) => (
                  <button key={v} className={legView === v ? "on" : undefined} onClick={() => setLegView(v)}>
                    {label}
                  </button>
                ))}
              </span>
            )}
            <label className="m3d-check">
              <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> Seguir
            </label>
            <label className="m3d-check">
              <input type="checkbox" checked={terrainOn} disabled={offline} onChange={(e) => setTerrainOn(e.target.checked)} /> Relieve
            </label>
          </div>
        )}
      </div>
    </div>
  );
}

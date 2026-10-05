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
import { useIsMobile } from "../../hooks/useMediaQuery";
import { usePersistedState } from "../../hooks/usePersistedState";
import { useUrlNumber } from "../../hooks/useUrlState";
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
import { DEMO_NODE_INFO, DEMO_TRACE_ID, demoTrace } from "./demoTrace";
import { t } from "../../tokens";

/**
 * Mapa 3D de una traza (traceroute): SOLO dibuja los nodos de esa traza —ni el
 * resto de la flota ni el grafo— para no sobrecargar la escena. Pilares en los
 * nodos, arcos elevados entre ellos coloreados por SNR y un pulso que recorre
 * la ida y la vuelta. Se abre desde la ventana de resultado del traceroute
 * (`?m3d.op=<id de operación>`) o eligiendo una traza reciente de la lista.
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

  // ── Datos ────────────────────────────────────────────────────────────
  const recent = useQuery({
    queryKey: ["traces", "recent"],
    queryFn: () => fetchTraces({ limit: 40, sinceHours: 24 * 30 }),
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

  const reached = useMemo(() => (recent.data ?? []).filter((x) => x.reached), [recent.data]);
  const demo = useMemo(() => demoTrace(), []);
  const trace: TraceOut | null =
    (isDemo ? demo : undefined) ??
    byOp.data?.[0] ??
    (traceParam != null ? (reached.find((x) => x.id === traceParam) ?? byId.data) : undefined) ??
    (opParam == null && traceParam == null ? reached[0] : undefined) ??
    null;
  const waitingForOp = opParam != null && !byOp.data?.length && byOp.isFetching;

  const info = useMemo(() => {
    const m = new Map<string, { name: string; pos: LngLat | null }>();
    for (const s of summaries) {
      const p = s.last_position;
      m.set(s.node.node_id, {
        name: s.node.long_name || s.node.short_name || s.node.node_id,
        pos: p ? [p.longitude, p.latitude] : null,
      });
    }
    if (isDemo) for (const [id, v] of DEMO_NODE_INFO) m.set(id, v);
    return m;
  }, [summaries, isDemo]);
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

  const hops = useMemo(() => (trace ? hopsOf(trace) : []), [trace]);
  const drawable = scene?.hops.length ?? 0;
  const hasBack = hops.some((h) => h.leg === 1);
  const headLeg = hops.find((h) => h.seq === headHop)?.leg;

  // ── UI ───────────────────────────────────────────────────────────────
  return (
    <div className="ws" style={{ flexDirection: isMobile ? "column" : "row" }}>
      <aside
        className="panel"
        style={isMobile ? { maxHeight: "34%", flexShrink: 0 } : { width: 310, flexShrink: 0 }}
      >
        <div className="panel-head">
          <span className="panel-title">Mapa 3D · traza</span>
        </div>
        <div className="ws-scroll" style={{ padding: 10, display: "flex", flexDirection: "column", gap: 10 }}>
          <label style={{ fontSize: 11, color: t.textDim }}>
            TRAZA
            <select
              className="input"
              style={{ width: "100%", marginTop: 4 }}
              value={trace?.id ?? ""}
              onChange={(e) => {
                setOpParam(null);
                setTraceParam(e.target.value ? Number(e.target.value) : null);
              }}
            >
              {!trace && <option value="">—</option>}
              <option value={DEMO_TRACE_ID}>★ Demo · 8 nodos (ejemplo, no real)</option>
              {trace && !isDemo && !reached.some((x) => x.id === trace.id) && (
                <option value={trace.id}>
                  {nameOf(trace.origin_id)} → {nameOf(trace.target_id)} · {relativeTime(trace.received_at)}
                </option>
              )}
              {reached.map((x) => (
                <option key={x.id} value={x.id}>
                  {nameOf(x.origin_id)} → {nameOf(x.target_id)} · {x.route.length} salto
                  {x.route.length === 1 ? "" : "s"} · {relativeTime(x.received_at)}
                </option>
              ))}
            </select>
          </label>

          {waitingForOp && <div className="empty">Esperando a que la traza quede registrada…</div>}
          {!trace && !waitingForOp && (
            <div className="empty">
              Aún no hay trazas con resultado. Lanza un traceroute desde el Inspector de un nodo y vuelve aquí,
              o elige la traza «★ Demo» del selector para ver cómo luce.
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
          <div style={{ fontSize: 10.5, color: t.textFaint, marginTop: "auto" }}>
            Solo se dibujan los nodos de la traza. Color del arco = SNR del salto (verde bueno → rojo
            muy débil).
          </div>
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
        </div>
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

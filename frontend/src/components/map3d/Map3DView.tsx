import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MlMap, Marker } from "maplibre-gl";
// MapLibre 6 es ESM puro con el worker en un módulo aparte: Vite no lo resuelve
// solo (en dev falla con "Worker failed to load"), así que se empaqueta con
// `?worker&url` y se le indica a MapLibre dónde está.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import { fetchTrace, fetchTraces, type NodeSummaryOut, type TraceOut } from "../../api/client";
import { useIsMobile } from "../../hooks/useMediaQuery";
import { useUrlNumber } from "../../hooks/useUrlState";
import { relativeTime } from "../../time";
import {
  BASE_STYLE_URL,
  FALLBACK_STYLE,
  TERRAIN_ATTRIBUTION,
  TERRAIN_EXAGGERATION,
  TERRAIN_TILES,
} from "./map3dConfig";
import {
  buildArc,
  disc,
  distanceM,
  hopsOf,
  nodesOf,
  ribbonCenter,
  snrColor,
  type LngLat,
  type Ribbon,
} from "./traceGeometry";
import { t } from "../../tokens";

/**
 * Mapa 3D de una traza (traceroute): SOLO dibuja los nodos de esa traza —ni el
 * resto de la flota ni el grafo— para no sobrecargar la escena. Pilares en los
 * nodos, arcos elevados entre ellos coloreados por SNR y un pulso que recorre
 * la ida y la vuelta. Se abre desde la ventana de resultado del traceroute
 * (`?m3d.op=<id de operación>`) o eligiendo una traza reciente de la lista.
 */

maplibregl.setWorkerUrl(workerUrl);

const STEPS = 22; // prismas por arco
const HOP_SECONDS = 1.8; // duración de un salto a velocidad 1×
const TRAIL = 16; // prismas que dejan estela tras la cabeza
const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

const ROLE_COLOR = { origin: "#4c8dff", dest: "#2ea06a", hop: "#aab3c5" } as const;

function polyFeature(ring: LngLat[], props: Record<string, unknown>): GeoJSON.Feature {
  return { type: "Feature", properties: props, geometry: { type: "Polygon", coordinates: [ring] } };
}

interface Scene {
  ribbons: Ribbon[];
  /** salto → índice de prisma donde empieza (para saber en qué salto va el pulso) */
  hopOfRibbon: number[];
  missing: string[];
  bounds: maplibregl.LngLatBounds | null;
  nodeIds: string[];
}

function buildScene(
  trace: TraceOut,
  pos: Map<string, LngLat>,
): Scene & { pillars: GeoJSON.Feature[]; pillarH: number; halfW: number } {
  const hops = hopsOf(trace);
  const ids = nodesOf(hops);
  const located = ids.filter((id) => pos.has(id));
  const missing = ids.filter((id) => !pos.has(id));
  // extensión de la escena → tamaños relativos (la misma traza se ve igual de
  // bien con 300 m que con 30 km)
  let ext = 200;
  for (const a of located) for (const b of located) ext = Math.max(ext, distanceM(pos.get(a)!, pos.get(b)!));
  const pillarH = Math.min(1500, Math.max(50, ext * 0.07));
  const halfW = Math.min(130, Math.max(6, ext * 0.0065));

  const ribbons: Ribbon[] = [];
  const hopOfRibbon: number[] = [];
  for (const h of hops) {
    const a = pos.get(h.from);
    const b = pos.get(h.to);
    if (!a || !b) continue;
    const len = distanceM(a, b);
    const arc = buildArc(a, b, {
      steps: STEPS,
      pillarH,
      peak: Math.min(1200, Math.max(50, len * 0.25)),
      halfW,
      side: (h.leg === 0 ? -1 : 1) * halfW * 1.8,
      hop: h.seq,
      leg: h.leg,
      color: snrColor(h.snr),
      orderStart: ribbons.length,
    });
    ribbons.push(...arc);
    for (let i = 0; i < arc.length; i++) hopOfRibbon.push(h.seq);
  }

  const pillars = located.map((id) =>
    polyFeature(disc(pos.get(id)!, halfW * 2.4), {
      height: pillarH,
      color: id === trace.origin_id ? ROLE_COLOR.origin : id === trace.target_id ? ROLE_COLOR.dest : ROLE_COLOR.hop,
    }),
  );
  let bounds: maplibregl.LngLatBounds | null = null;
  for (const id of located) {
    const p = pos.get(id)!;
    bounds = bounds ? bounds.extend(p) : new maplibregl.LngLatBounds(p, p);
  }
  return { ribbons, hopOfRibbon, missing, bounds, nodeIds: ids, pillars, pillarH, halfW };
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

  const byId = useQuery({
    queryKey: ["traces", "id", traceParam],
    queryFn: () => fetchTrace(traceParam!),
    enabled: traceParam != null,
    retry: false,
  });

  const reached = useMemo(() => (recent.data ?? []).filter((x) => x.reached), [recent.data]);
  const trace: TraceOut | null =
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
    return m;
  }, [summaries]);
  const nameOf = (id: string) => info.get(id)?.name ?? id;

  const scene = useMemo(() => {
    if (!trace) return null;
    const pos = new Map<string, LngLat>();
    for (const [id, v] of info) if (v.pos) pos.set(id, v.pos);
    return buildScene(trace, pos);
  }, [trace, info]);

  // ── Estado de la reproducción ────────────────────────────────────────
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [follow, setFollow] = useState(false);
  const [terrainOn, setTerrainOn] = useState(true);
  const [offline, setOffline] = useState(false);
  const [ready, setReady] = useState(false);
  const [headHop, setHeadHop] = useState(-1);
  const [progressPct, setProgressPct] = useState(0);

  const hostRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const markersRef = useRef<Marker[]>([]);
  const progressRef = useRef(0); // en prismas (float)
  const lastIdxRef = useRef(-1);
  const sceneRef = useRef(scene);
  sceneRef.current = scene;
  const followRef = useRef(follow);
  followRef.current = follow;
  const terrainRef = useRef(terrainOn);
  terrainRef.current = terrainOn;

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
            tiles: TERRAIN_TILES,
            encoding: "terrarium",
            tileSize: 256,
            maxzoom: 15,
            attribution: id === "dem" ? TERRAIN_ATTRIBUTION : undefined,
          });
        }
        const firstSymbol = map.getStyle().layers.find((l) => l.type === "symbol")?.id;
        map.addLayer(
          {
            id: "hillshade",
            type: "hillshade",
            source: "dem-shade",
            paint: {
              "hillshade-exaggeration": 0.8,
              "hillshade-shadow-color": "#000000",
              "hillshade-highlight-color": "#5b6c8f",
              "hillshade-accent-color": "#000000",
            },
          },
          firstSymbol,
        );
        if (terrainRef.current) map.setTerrain({ source: "dem", exaggeration: TERRAIN_EXAGGERATION });
      }
      for (const id of ["pillars", "arcs-static", "arcs-live", "arcs-head", "head-shadow"]) {
        map.addSource(id, { type: "geojson", data: EMPTY });
      }
      const extrusion = (id: string, opacity: number, color?: string) =>
        map.addLayer({
          id,
          type: "fill-extrusion",
          source: id,
          paint: {
            "fill-extrusion-color": color ?? ["get", "color"],
            "fill-extrusion-height": ["get", "height"],
            "fill-extrusion-base": ["coalesce", ["get", "base"], 0],
            "fill-extrusion-opacity": opacity,
            "fill-extrusion-vertical-gradient": true,
          },
        });
      extrusion("pillars", 0.88);
      extrusion("arcs-static", 0.3);
      extrusion("arcs-live", 0.95);
      extrusion("arcs-head", 1, "#ffffff");
      map.addLayer({
        id: "head-shadow",
        type: "circle",
        source: "head-shadow",
        paint: { "circle-radius": 14, "circle-color": "#ffffff", "circle-opacity": 0.25, "circle-blur": 1, "circle-pitch-alignment": "map" },
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
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // ── Relieve activable ────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.getSource("dem")) return;
    map.setTerrain(terrainOn ? { source: "dem", exaggeration: TERRAIN_EXAGGERATION } : null);
  }, [terrainOn, ready]);

  // ── Escena estática: pilares, arcos tenues, etiquetas, encuadre ──────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];
    const live = (id: string) => map.getSource(id) as GeoJSONSource | undefined;
    for (const id of ["arcs-live", "arcs-head", "head-shadow"]) live(id)?.setData(EMPTY);
    progressRef.current = 0;
    lastIdxRef.current = -1;
    setHeadHop(-1);
    setProgressPct(0);

    if (!trace || !scene) {
      live("pillars")?.setData(EMPTY);
      live("arcs-static")?.setData(EMPTY);
      return;
    }
    const { pillars, ribbons } = scene as ReturnType<typeof buildScene>;
    live("pillars")?.setData({ type: "FeatureCollection", features: pillars });
    live("arcs-static")?.setData({
      type: "FeatureCollection",
      features: ribbons.map((r) => polyFeature(r.ring, { color: r.color, base: r.base, height: r.height })),
    });

    for (const id of scene.nodeIds) {
      const p = info.get(id)?.pos;
      if (!p) continue;
      const role = id === trace.origin_id ? "ORIGEN" : id === trace.target_id ? "DESTINO" : "SALTO";
      const el = document.createElement("div");
      el.className = "m3d-label";
      el.innerHTML = `<small>${role}</small><b></b>`;
      el.querySelector("b")!.textContent = nameOf(id);
      el.addEventListener("click", () => onOpenNode(id));
      markersRef.current.push(
        new maplibregl.Marker({ element: el, anchor: "bottom", offset: [0, -((scene as ReturnType<typeof buildScene>).pillarH > 0 ? 6 : 0)] })
          .setLngLat(p)
          .addTo(map),
      );
    }
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
  }, [scene, trace, ready]);

  // ── Animación del pulso ──────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !scene || scene.ribbons.length === 0) return;
    const rate = (STEPS / HOP_SECONDS) * speed; // prismas por segundo
    const total = scene.ribbons.length;
    let raf = 0;
    let prev = performance.now();
    const src = (id: string) => map.getSource(id) as GeoJSONSource | undefined;

    const draw = (idx: number) => {
      const s = sceneRef.current;
      if (!s) return;
      const from = Math.max(0, idx - TRAIL);
      const fc = (rs: Ribbon[]): GeoJSON.FeatureCollection => ({
        type: "FeatureCollection",
        features: rs.map((r) => polyFeature(r.ring, { color: r.color, base: r.base, height: r.height })),
      });
      src("arcs-live")?.setData(fc(s.ribbons.slice(from, idx)));
      const head = s.ribbons[idx];
      const lift = (r: Ribbon): Ribbon => ({ ...r, base: r.base, height: r.height + 3 });
      src("arcs-head")?.setData(fc([lift(head)]));
      const c = ribbonCenter(head);
      src("head-shadow")?.setData({
        type: "FeatureCollection",
        features: [{ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: c.lngLat } }],
      });
      setHeadHop(s.hopOfRibbon[idx]);
      setProgressPct((idx / (total - 1)) * 100);
      if (followRef.current) map.easeTo({ center: c.lngLat, duration: 450, easing: (x) => x });
    };

    const frame = (now: number) => {
      const dt = Math.min(0.1, (now - prev) / 1000);
      prev = now;
      if (playing) progressRef.current = Math.min(total - 1, progressRef.current + dt * rate);
      const idx = Math.floor(progressRef.current);
      if (idx !== lastIdxRef.current) {
        lastIdxRef.current = idx;
        draw(idx);
      }
      if (playing && progressRef.current >= total - 1) setPlaying(false);
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [scene, ready, playing, speed]);

  const seek = (pct: number) => {
    if (!scene) return;
    progressRef.current = (pct / 100) * (scene.ribbons.length - 1);
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
  const drawable = scene?.ribbons.length ?? 0;

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
              {trace && !reached.some((x) => x.id === trace.id) && (
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
              Aún no hay trazas con resultado. Lanza un traceroute desde el Inspector de un nodo y vuelve aquí.
            </div>
          )}

          {trace && (
            <>
              <div style={{ fontSize: 11.5, color: t.textDim }}>
                {trace.source === "active" ? "Traceroute activo" : "Oído en la malla"} · pasarela {trace.gateway_id ?? "—"}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {hops.map((h) => {
                  const located = info.get(h.from)?.pos && info.get(h.to)?.pos;
                  return (
                    <div
                      key={h.seq}
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
                      <span style={{ color: t.textFaint, width: 16 }}>{h.leg === 0 ? "→" : "←"}</span>
                      <span style={{ flex: 1, overflowWrap: "anywhere" }}>
                        {nameOf(h.from)} → {nameOf(h.to)}
                      </span>
                      <span className="mono" style={{ color: snrColor(h.snr) }}>
                        {h.snr != null ? `${h.snr} dB` : "—"}
                      </span>
                    </div>
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
            muy débil). La altura de los arcos es ilustrativa: no es la ruta de radio real, que se
            desconoce.
          </div>
        </div>
      </aside>

      <div style={{ flex: 1, minWidth: 0, minHeight: 0, position: "relative" }}>
        <div ref={hostRef} style={{ position: "absolute", inset: 0 }} />
        {offline && (
          <div className="m3d-note">
            Sin conexión con el servidor de mapas: fondo plano y sin relieve (el dibujo de la traza sigue funcionando).
          </div>
        )}
        {trace && drawable > 0 && (
          <div className="m3d-controls">
            <button className="btn" onClick={() => (progressRef.current >= drawable - 1 ? replay() : setPlaying((p) => !p))}>
              {playing ? "⏸" : progressRef.current >= drawable - 1 ? "↻" : "▶"}
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

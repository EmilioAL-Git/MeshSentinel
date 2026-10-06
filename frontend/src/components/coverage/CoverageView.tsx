import { useEffect, useMemo, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, ImageSource, Map as MlMap } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import type { NodeSummaryOut } from "../../api/client";
import { useIsMobile } from "../../hooks/useMediaQuery";
import { useUrlString } from "../../hooks/useUrlState";
import {
  BASE_STYLE_URL,
  DEM,
  FALLBACK_STYLE,
  SATELLITE_ATTRIBUTION,
  SATELLITE_TILES,
} from "../map3d/map3dConfig";
import { NodeSearch, nodeLabel } from "../map3d/NodeSearch";
import type { LngLat } from "../map3d/traceGeometry";
import {
  DEFAULT_PARAMS,
  MARGIN_BANDS,
  MODEM_PRESETS,
  computeCoverage,
  eirpDbm,
  loadElevationGrid,
  marginAt,
  paintOverlay,
  sensitivityDbm,
  type CoverageParams,
  type CoverageResult,
} from "./coverageModel";
import { t } from "../../tokens";

maplibregl.setWorkerUrl(workerUrl);

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };
const BAND_CSS = MARGIN_BANDS.map((b) => `rgba(${b.rgba[0]},${b.rgba[1]},${b.rgba[2]},0.9)`);

function parsePt(raw: string | null): LngLat | null {
  if (!raw) return null;
  const [lat, lng] = raw.split(",").map(Number);
  return Number.isFinite(lat) && Number.isFinite(lng) ? [lng, lat] : null;
}

function Num({
  label,
  value,
  onChange,
  unit,
  step = 1,
  min,
  max,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  unit: string;
  step?: number;
  min?: number;
  max?: number;
}) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 2, fontSize: 11.5, color: t.textDim }}>
      {label}
      <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
        <input
          className="input mono"
          type="number"
          value={Number.isFinite(value) ? value : ""}
          step={step}
          min={min}
          max={max}
          style={{ width: "100%", minWidth: 0 }}
          onChange={(e) => {
            const n = e.target.valueAsNumber;
            if (Number.isFinite(n)) onChange(n);
          }}
        />
        <span style={{ fontSize: 11, color: t.textFaint, minWidth: 26 }}>{unit}</span>
      </span>
    </label>
  );
}

/** Bandas del Perfil topográfico del Mapa 3D + la frecuencia de SF Narrow (predeterminada). */
const FREQ_OPTIONS = [
  { value: 869.618, label: "869,618 MHz · SF Narrow" },
  ...[170, 433, 868, 915, 2400].map((f) => ({ value: f, label: `${f} MHz` })),
];

const fmtKm = (m: number) => (m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`);

/**
 * Calculador de cobertura 3D: eliges el emisor (un nodo o un punto del mapa),
 * introduces potencia, ganancias, frecuencia y alturas, y se dibuja sobre el
 * relieve la zona donde el enlace cierra (ver `coverageModel.ts` para el
 * modelo y sus límites).
 */
export function CoverageView({ summaries, onOpenNode }: { summaries: NodeSummaryOut[]; onOpenNode: (id: string) => void }) {
  const isMobile = useIsMobile();
  const hostRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const resultRef = useRef<CoverageResult | null>(null);
  const [ready, setReady] = useState(false);
  const [offline, setOffline] = useState(false);

  const [params, setParams] = useState<CoverageParams>(DEFAULT_PARAMS);
  const [presetId, setPresetId] = useState<string>(MODEM_PRESETS[0].id);
  const [satellite, setSatellite] = useState(true);
  const [exag, setExag] = useState(1.5);
  const [panelOpen, setPanelOpen] = useState(true);
  // El emisor vive en la URL (compartible): `cov.node` = nodo, `cov.pt` = "lat,lng"
  const [nodeParam, setNodeParam] = useUrlString("cov.node");
  const [ptParam, setPtParam] = useUrlString("cov.pt");
  const [mode, setMode] = useState<"node" | "point">(nodeParam || !ptParam ? "node" : "point");
  const full: CoverageParams = { ...DEFAULT_PARAMS, ...params };
  const set = <K extends keyof CoverageParams>(k: K, v: CoverageParams[K]) => setParams({ ...full, [k]: v });

  const nodeSummary = useMemo(
    () => (nodeParam ? summaries.find((s) => s.node.node_id === nodeParam) ?? null : null),
    [nodeParam, summaries],
  );
  const center: LngLat | null = useMemo(() => {
    if (mode === "node") {
      const p = nodeSummary?.last_position;
      return p ? [p.longitude, p.latitude] : null;
    }
    return parsePt(ptParam);
  }, [mode, nodeSummary, ptParam]);
  const centerKey = center ? `${center[0].toFixed(5)},${center[1].toFixed(5)}` : null;

  const [status, setStatus] = useState<"idle" | "loading" | "nodata">("idle");
  const [result, setResult] = useState<CoverageResult | null>(null);
  const [probe, setProbe] = useState<{ margin: number; distanceM: number; bearing: number } | null>(null);

  // ── Mapa (una vez) ─────────────────────────────────────────────────
  const [clickAction, setClickAction] = useState<"measure" | "place">("measure");
  const [customFreq, setCustomFreq] = useState(false);
  const [pin, setPin] = useState<LngLat | null>(null);
  const [pitch, setPitch] = useState(15);
  const pinMarkerRef = useRef<maplibregl.Marker | null>(null);
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const actionRef = useRef(clickAction);
  actionRef.current = clickAction;
  const centerRef = useRef<LngLat | null>(null);
  centerRef.current = center;
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const map = new maplibregl.Map({
      container: host,
      style: BASE_STYLE_URL,
      center: [-2.5, 39.5],
      zoom: 5,
      pitch: 15,
      bearing: 0,
      maxPitch: 80,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");

    let styleOk = false;
    const install = () => {
      styleOk = true;
      if (map.getSource("dem")) return;
      const layers = map.getStyle().layers;
      const firstSymbol = layers.find((l) => l.type === "symbol")?.id;
      const under = layers.find((l) => l.id === "waterway")?.id ?? firstSymbol;
      if (Object.keys(map.getStyle().sources ?? {}).length > 0) {
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
        map.addSource("sat", {
          type: "raster",
          tiles: SATELLITE_TILES,
          tileSize: 256,
          maxzoom: 13,
          attribution: SATELLITE_ATTRIBUTION,
        });
        map.addLayer({ id: "sat", type: "raster", source: "sat", layout: { visibility: "none" } }, under);
        map.addLayer(
          {
            id: "hillshade",
            type: "hillshade",
            source: "dem-shade",
            paint: { "hillshade-exaggeration": 0.7, "hillshade-shadow-color": "#000000", "hillshade-highlight-color": "#5b6c8f" },
          },
          under,
        );
        map.setTerrain({ source: "dem", exaggeration: 1.5 });
      }
      map.addSource("cov-nodes", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "cov-nodes",
        type: "circle",
        source: "cov-nodes",
        paint: {
          "circle-radius": 4.5,
          "circle-color": ["case", ["get", "covered"], "#3fd08a", "#8a93a3"],
          "circle-stroke-color": "#0b0e14",
          "circle-stroke-width": 1,
        },
      });
      setReady(true);
    };
    map.on("style.load", install);
    const fallback = () => {
      if (styleOk) return;
      styleOk = true;
      setOffline(true);
      map.setStyle(FALLBACK_STYLE);
    };
    map.on("error", () => !map.isStyleLoaded() && fallback());
    const timer = window.setTimeout(() => !map.isStyleLoaded() && fallback(), 9_000);

    map.on("click", (e) => {
      const placing = modeRef.current === "point" && (!centerRef.current || actionRef.current === "place");
      if (placing) {
        setMode("point");
        setNodeParam(null);
        setPtParam(`${e.lngLat.lat.toFixed(5)},${e.lngLat.lng.toFixed(5)}`);
      } else if (resultRef.current) {
        setPin([e.lngLat.lng, e.lngLat.lat]);
      }
    });
    let raf = 0;
    map.on("mousemove", (e) => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const res = resultRef.current;
        setProbe(res ? marginAt(res, e.lngLat.lng, e.lngLat.lat) : null);
      });
    });
    map.on("mouseout", () => setProbe(null));
    map.on("pitch", () => setPitch(Math.round(map.getPitch())));

    return () => {
      window.clearTimeout(timer);
      cancelAnimationFrame(raf);
      setReady(false);
      markerRef.current?.remove();
      markerRef.current = null;
      pinMarkerRef.current?.remove();
      pinMarkerRef.current = null;
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (map.getLayer("sat")) map.setLayoutProperty("sat", "visibility", satellite ? "visible" : "none");
  }, [satellite, ready]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.getSource("dem")) return;
    map.setTerrain({ source: "dem", exaggeration: exag });
  }, [exag, ready]);
  useEffect(() => {
    const map = mapRef.current;
    if (map) map.getCanvas().style.cursor = result || mode === "point" ? "crosshair" : "";
  }, [mode, ready, result]);

  // ── Marcador del emisor (arrastrable) ──────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (!center) {
      markerRef.current?.remove();
      markerRef.current = null;
      return;
    }
    if (!markerRef.current) {
      const el = document.createElement("div");
      el.style.cssText =
        "width:18px;height:18px;border-radius:50%;background:var(--accent);border:2px solid #fff;box-shadow:0 0 0 4px rgba(90,160,255,.35)";
      const m = new maplibregl.Marker({ element: el, draggable: true }).setLngLat(center).addTo(map);
      m.on("dragend", () => {
        const ll = m.getLngLat();
        setMode("point");
        setNodeParam(null);
        setPtParam(`${ll.lat.toFixed(5)},${ll.lng.toFixed(5)}`);
      });
      markerRef.current = m;
    } else {
      markerRef.current.setLngLat(center);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [centerKey, ready]);

  // ── Cálculo (con antirrebote; el resultado obsoleto se descarta) ────
  const fittedFor = useRef<string | null>(null);
  const paramsKey = JSON.stringify(full);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !center) {
      resultRef.current = null;
      setResult(null);
      setStatus("idle");
      return;
    }
    let cancelled = false;
    setStatus("loading");
    const timer = window.setTimeout(async () => {
      const grid = await loadElevationGrid(center, full.radiusKm * 1000);
      if (cancelled) return;
      const res = grid ? computeCoverage(center, grid, full) : null;
      if (!res) {
        resultRef.current = null;
        setResult(null);
        setStatus("nodata");
        return;
      }
      resultRef.current = res;
      setResult(res);
      setStatus("idle");
      const { canvas, coordinates } = paintOverlay(res);
      const url = canvas.toDataURL("image/png");
      const src = map.getSource("cov-img") as ImageSource | undefined;
      if (src) {
        src.updateImage({ url, coordinates });
      } else {
        map.addSource("cov-img", { type: "image", url, coordinates });
        const first = map.getStyle().layers.find((l) => l.type === "symbol")?.id;
        map.addLayer({ id: "cov-img", type: "raster", source: "cov-img", paint: { "raster-fade-duration": 0, "raster-resampling": "linear" } }, first);
        if (map.getLayer("cov-nodes")) map.moveLayer("cov-nodes");
      }
      if (fittedFor.current !== centerKey) {
        fittedFor.current = centerKey;
        const lngs = coordinates.map((c) => c[0]);
        const lats = coordinates.map((c) => c[1]);
        map.fitBounds([[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]], {
          padding: isMobile ? 20 : { top: 40, bottom: 40, left: 340, right: 40 },
          pitch: 15,
          duration: 900,
        });
      }
    }, 450);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [centerKey, paramsKey, ready]);

  // ── Nodos conocidos: ¿caen dentro de la cobertura prevista? ─────────
  const nodeStats = useMemo(() => {
    if (!result) return null;
    const feats: GeoJSON.Feature[] = [];
    let inside = 0;
    let total = 0;
    for (const s of summaries) {
      const p = s.last_position;
      if (!p || s.node.is_ignored) continue;
      const hit = marginAt(result, p.longitude, p.latitude);
      if (!hit) continue;
      total++;
      const covered = hit.margin >= 0;
      if (covered) inside++;
      feats.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: [p.longitude, p.latitude] },
        properties: { covered, name: nodeLabel(s) },
      });
    }
    return { inside, total, feats };
  }, [result, summaries]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource("cov-nodes") as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: nodeStats?.feats ?? [],
    });
  }, [nodeStats, ready]);

  const pinInfo = useMemo(() => {
    if (!pin || !result) return null;
    const hit = marginAt(result, pin[0], pin[1]);
    if (!hit) return { outside: true as const };
    const p = result.params;
    const rssi = hit.margin + p.sensitivityDbm + p.fadeMarginDb;
    return { outside: false as const, ...hit, rssi, pathLoss: result.eirpDbm + p.rxGainDbi - rssi };
  }, [pin, result]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (!pin) {
      pinMarkerRef.current?.remove();
      pinMarkerRef.current = null;
      return;
    }
    if (!pinMarkerRef.current) {
      const el = document.createElement("div");
      el.style.cssText = "width:12px;height:12px;border-radius:50%;background:#fff;border:3px solid #e5484d;box-shadow:0 0 0 2px #0b0e14";
      pinMarkerRef.current = new maplibregl.Marker({ element: el }).setLngLat(pin).addTo(map);
    } else {
      pinMarkerRef.current.setLngLat(pin);
    }
  }, [pin, ready]);
  const rssiOf = (m: number) => m + full.sensitivityDbm + full.fadeMarginDb;

  const preset = MODEM_PRESETS.find((p) => p.id === presetId) ?? MODEM_PRESETS[0];
  const eirp = eirpDbm(full);

  return (
    <div className="ws" style={{ flexDirection: isMobile ? "column" : "row" }}>
      <aside
        className="panel"
        style={isMobile ? { maxHeight: panelOpen ? "55%" : undefined, flexShrink: 0 } : { width: 320, flexShrink: 0 }}
      >
        <div className="panel-head">
          <span className="panel-title">Cobertura 3D</span>
          {isMobile && (
            <button className="btn" style={{ marginLeft: "auto" }} onClick={() => setPanelOpen((o) => !o)} aria-expanded={panelOpen}>
              {panelOpen ? "▴" : "▾"}
            </button>
          )}
        </div>
        <div
          className="ws-scroll"
          style={{ padding: 10, display: isMobile && !panelOpen ? "none" : "flex", flexDirection: "column", gap: 12 }}
        >
          <div>
            <div style={{ fontSize: 10.5, letterSpacing: "0.08em", fontWeight: 650, color: t.accent, marginBottom: 4 }}>EMISOR</div>
            <span className="seg" role="group" aria-label="Origen del emisor" style={{ display: "flex" }}>
              <button style={{ flex: 1 }} className={mode === "node" ? "on" : undefined} onClick={() => setMode("node")}>
                Nodo existente
              </button>
              <button style={{ flex: 1 }} className={mode === "point" ? "on" : undefined} onClick={() => setMode("point")}>
                Punto en el mapa
              </button>
            </span>
            {center && (
              <div style={{ marginTop: 8 }}>
                <div style={{ fontSize: 11.5, color: t.textDim, marginBottom: 3 }}>Al hacer clic en el mapa</div>
                <span className="seg" role="group" aria-label="Acción del clic" style={{ display: "flex" }}>
                  <button style={{ flex: 1 }} className={clickAction === "measure" || mode === "node" ? "on" : undefined} onClick={() => setClickAction("measure")}>
                    Medir señal
                  </button>
                  <button
                    style={{ flex: 1 }}
                    className={clickAction === "place" && mode === "point" ? "on" : undefined}
                    disabled={mode === "node"}
                    title={mode === "node" ? "Cambia a «Punto en el mapa» para mover el emisor con clic" : undefined}
                    onClick={() => setClickAction("place")}
                  >
                    Mover emisor
                  </button>
                </span>
              </div>
            )}
            {mode === "node" ? (
              <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
                {nodeSummary && (
                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    <button className="btn ghost" style={{ flex: 1, textAlign: "left" }} onClick={() => onOpenNode(nodeSummary.node.node_id)}>
                      {nodeLabel(nodeSummary)}
                    </button>
                    <button className="btn" onClick={() => setNodeParam(null)} title="Quitar">
                      ✕
                    </button>
                  </div>
                )}
                {nodeSummary && !nodeSummary.last_position && (
                  <div style={{ color: "var(--warn)", fontSize: 11.5 }}>
                    Este nodo no tiene posición. Elige otro o usa «Punto en el mapa».
                  </div>
                )}
                {!nodeSummary && (
                  <NodeSearch
                    summaries={summaries.filter((s) => s.last_position)}
                    onPick={(id) => {
                      setPtParam(null);
                      setNodeParam(id);
                    }}
                    placeholder="Buscar nodo con posición…"
                  />
                )}
              </div>
            ) : (
              <div style={{ marginTop: 8, fontSize: 12, color: t.textDim, lineHeight: 1.45 }}>
                {center ? (
                  <span className="mono">
                    {center[1].toFixed(5)}, {center[0].toFixed(5)}
                  </span>
                ) : (
                  "Haz clic en el mapa para colocar el emisor."
                )}{" "}
                {center && "Arrastra el marcador para moverlo."}
              </div>
            )}
          </div>

          <div>
            <div style={{ fontSize: 10.5, letterSpacing: "0.08em", fontWeight: 650, color: t.accent, marginBottom: 6 }}>TRANSMISOR</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <Num label="Potencia" unit="dBm" value={full.txPowerDbm} onChange={(v) => set("txPowerDbm", v)} min={0} max={36} />
              <Num label="Ganancia antena" unit="dBi" value={full.txGainDbi} onChange={(v) => set("txGainDbi", v)} step={0.5} min={-5} max={30} />
              <Num label="Pérdida cable" unit="dB" value={full.cableLossDb} onChange={(v) => set("cableLossDb", v)} step={0.5} min={0} max={20} />
              <Num label="Altura antena" unit="m" value={full.mastM} onChange={(v) => set("mastM", v)} min={0} max={200} />
            </div>
            <div style={{ fontSize: 11.5, color: t.textDim, marginTop: 6 }}>
              PIRE: <span className="mono" style={{ color: t.text }}>{eirp.toFixed(1)} dBm</span> ({(10 ** (eirp / 10) / 1000).toFixed(2)} W)
            </div>
          </div>

          <div>
            <div style={{ fontSize: 10.5, letterSpacing: "0.08em", fontWeight: 650, color: t.accent, marginBottom: 6 }}>RADIO Y RECEPTOR</div>
            <label style={{ display: "flex", flexDirection: "column", gap: 2, fontSize: 11.5, color: t.textDim, marginBottom: 8 }}>
              Preset de módem
              <select
                className="input"
                value={presetId}
                onChange={(e) => {
                  setPresetId(e.target.value);
                  const p = MODEM_PRESETS.find((x) => x.id === e.target.value)!;
                  if (p.freqMHz) setCustomFreq(false);
                  setParams({
                    ...full,
                    sensitivityDbm: Math.round(sensitivityDbm(p) * 10) / 10,
                    ...(p.freqMHz ? { freqMHz: p.freqMHz } : {}),
                  });
                }}
              >
                {MODEM_PRESETS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <label style={{ display: "flex", flexDirection: "column", gap: 2, fontSize: 11.5, color: t.textDim, gridColumn: "1 / -1" }}>
                Frecuencia
                <select
                  className="input"
                  value={customFreq || !FREQ_OPTIONS.some((f) => f.value === full.freqMHz) ? "custom" : String(full.freqMHz)}
                  onChange={(e) => {
                    if (e.target.value === "custom") setCustomFreq(true);
                    else {
                      setCustomFreq(false);
                      set("freqMHz", Number(e.target.value));
                    }
                  }}
                >
                  {FREQ_OPTIONS.map((f) => (
                    <option key={f.value} value={f.value}>
                      {f.label}
                    </option>
                  ))}
                  <option value="custom">Personalizada…</option>
                </select>
              </label>
              {(customFreq || !FREQ_OPTIONS.some((f) => f.value === full.freqMHz)) && (
                <Num label="Frecuencia personalizada" unit="MHz" value={full.freqMHz} onChange={(v) => set("freqMHz", v)} step={0.001} min={100} max={2500} />
              )}
              <Num label="Sensibilidad RX" unit="dBm" value={full.sensitivityDbm} onChange={(v) => set("sensitivityDbm", v)} step={0.5} />
              <Num label="Ganancia antena RX" unit="dBi" value={full.rxGainDbi} onChange={(v) => set("rxGainDbi", v)} step={0.5} min={-5} max={30} />
              <Num label="Altura RX" unit="m" value={full.rxHeightM} onChange={(v) => set("rxHeightM", v)} step={0.5} min={0} max={100} />
              <Num label="Margen desvanec." unit="dB" value={full.fadeMarginDb} onChange={(v) => set("fadeMarginDb", v)} min={0} max={40} />
              <Num label="Pérdida entorno" unit="dB" value={full.extraLossDb} onChange={(v) => set("extraLossDb", v)} min={0} max={40} />
              <Num label="Radio de cálculo" unit="km" value={full.radiusKm} onChange={(v) => set("radiusKm", Math.min(300, Math.max(1, v)))} min={1} max={300} />
            </div>
            <div style={{ fontSize: 11, color: t.textFaint, marginTop: 6, lineHeight: 1.4 }}>
              Sensibilidad teórica de {preset.label.split(" (")[0]}: {sensitivityDbm(preset).toFixed(1)} dBm (NF 6 dB).
            </div>
            <button className="btn ghost" style={{ marginTop: 6 }} onClick={() => (setParams(DEFAULT_PARAMS), setPresetId(MODEM_PRESETS[0].id), setCustomFreq(false))}>
              Restablecer valores
            </button>
          </div>

          <div>
            <div style={{ fontSize: 10.5, letterSpacing: "0.08em", fontWeight: 650, color: t.accent, marginBottom: 6 }}>RESULTADO</div>
            {status === "loading" && <div className="empty">Calculando…</div>}
            {status === "nodata" && <div className="empty">Sin datos de relieve para esta zona (¿sin conexión?).</div>}
            {!center && status === "idle" && <div className="empty">Elige un emisor para calcular.</div>}
            {result && status !== "nodata" && (
              <div style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12.5 }}>
                <div>Terreno bajo el emisor: <b className="mono">{Math.round(result.groundM)} m</b> (+{full.mastM} m)</div>
                <div>Alcance máximo: <b className="mono">{fmtKm(result.maxReachM)}</b> hacia {Math.round(result.maxReachBearing)}°</div>
                <div>Alcance medio: <b className="mono">{fmtKm(result.meanReachM)}</b></div>
                <div>Área cubierta: <b className="mono">{result.areaKm2.toFixed(1)} km²</b></div>
                {nodeStats && nodeStats.total > 0 && (
                  <div>
                    Nodos conocidos en la zona: <b className="mono">{nodeStats.inside}</b> de {nodeStats.total} dentro de cobertura prevista
                  </div>
                )}
                {result.maxReachM >= full.radiusKm * 1000 * 0.98 && (
                  <div style={{ color: "var(--warn)", fontSize: 11.5 }}>
                    Hay cobertura hasta el borde: sube el radio de cálculo para ver el alcance real.
                  </div>
                )}
              </div>
            )}
          </div>

          <div style={{ fontSize: 11, color: t.textFaint, lineHeight: 1.45 }}>
            Modelo: espacio libre + difracción de un filo equivalente (Bullington) + 1 dB/km empírico en zonas de sombra + curvatura k=4/3 sobre el relieve del mapa. No incluye
            vegetación, edificios ni multitrayecto: usa «Pérdida entorno» para aproximarlos. Es una estimación para planificar,
            no una garantía de enlace.
          </div>
        </div>
      </aside>

      <div style={{ flex: 1, minWidth: 0, minHeight: 0, position: "relative" }}>
        <div ref={hostRef} style={{ position: "absolute", inset: 0 }} />
        <div
          className="panel"
          style={{ position: "absolute", left: 10, bottom: 28, padding: "6px 10px", display: "flex", flexDirection: "column", gap: 3, fontSize: 11.5 }}
        >
          <span style={{ fontWeight: 650, fontSize: 10.5, letterSpacing: "0.08em" }}>MARGEN DE ENLACE</span>
          {MARGIN_BANDS.map((b, i) => (
            <span key={b.label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ width: 12, height: 12, borderRadius: 2, background: BAND_CSS[i] }} />
              {b.label}
            </span>
          ))}
          <span style={{ display: "flex", alignItems: "center", gap: 6, color: t.textDim }}>
            <span style={{ width: 9, height: 9, borderRadius: "50%", background: "#3fd08a" }} /> nodo en cobertura
            <span style={{ width: 9, height: 9, borderRadius: "50%", background: "#8a93a3", marginLeft: 6 }} /> fuera
          </span>
        </div>
        <div className="panel" style={{ position: "absolute", right: 10, top: 10, padding: "6px 10px", display: "flex", gap: 10, alignItems: "center", fontSize: 12, marginRight: 40 }}>
          <label style={{ display: "flex", gap: 4, alignItems: "center" }}>
            <input type="checkbox" checked={satellite} disabled={offline} onChange={(e) => setSatellite(e.target.checked)} /> Satélite
          </label>
          <label style={{ display: "flex", gap: 4, alignItems: "center" }} title="Inclinación de la vista (0° = vista cenital)">
            Inclinación {pitch}°
            <input type="range" min={0} max={80} step={1} value={pitch} onChange={(e) => mapRef.current?.setPitch(Number(e.target.value))} style={{ width: 80 }} />
          </label>
          <label style={{ display: "flex", gap: 4, alignItems: "center" }} title="Exageración vertical del relieve">
            Relieve ×{exag}
            <input type="range" min={1} max={4} step={0.5} value={exag} disabled={offline} onChange={(e) => setExag(Number(e.target.value))} style={{ width: 70 }} />
          </label>
        </div>
        {(pin || probe) && (
          <div style={{ position: "absolute", right: 10, bottom: 28, display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" }}>
            {pin && (
              <div className="panel" style={{ padding: "8px 12px", fontSize: 12.5, minWidth: 210, display: "flex", flexDirection: "column", gap: 3 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontWeight: 650, fontSize: 10.5, letterSpacing: "0.08em" }}>SEÑAL EN EL PUNTO</span>
                  <button className="btn" style={{ marginLeft: "auto", padding: "0 6px" }} onClick={() => setPin(null)} title="Quitar punto">
                    ✕
                  </button>
                </div>
                {pinInfo && !pinInfo.outside ? (
                  <>
                    <div className="mono" style={{ fontSize: 20, fontWeight: 650, color: pinInfo.margin >= 0 ? t.ok : "var(--crit)" }}>
                      {pinInfo.rssi.toFixed(1)} dBm
                    </div>
                    <div>
                      {pinInfo.margin >= 0 ? (
                        <>Margen: <b className="mono">+{pinInfo.margin.toFixed(1)} dB</b> · hay enlace</>
                      ) : (
                        <>Faltan <b className="mono">{(-pinInfo.margin).toFixed(1)} dB</b> · sin enlace</>
                      )}
                    </div>
                    <div style={{ color: t.textDim }}>
                      {fmtKm(pinInfo.distanceM)} · rumbo {Math.round(pinInfo.bearing)}° · pérdida {pinInfo.pathLoss.toFixed(1)} dB
                    </div>
                  </>
                ) : (
                  <div style={{ color: t.textDim }}>{result ? "Fuera del radio de cálculo o sin datos de relieve." : "Calculando…"}</div>
                )}
              </div>
            )}
            {probe && (
              <div className="panel mono" style={{ padding: "6px 10px", fontSize: 12 }}>
                {fmtKm(probe.distanceM)} · {Math.round(probe.bearing)}° ·{" "}
                <b style={{ color: probe.margin >= 0 ? t.ok : t.textDim }}>
                  {rssiOf(probe.margin).toFixed(1)} dBm ({probe.margin >= 0 ? "+" : ""}
                  {probe.margin.toFixed(1)} dB)
                </b>
              </div>
            )}
          </div>
        )}
        {offline && (
          <div className="panel" style={{ position: "absolute", left: 10, top: 10, padding: "6px 10px", fontSize: 12, color: "var(--warn)" }}>
            Sin conexión a los mapas base: se muestra un fondo plano sin relieve.
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Modelo de cobertura radioeléctrica (puro, sin React ni MapLibre).
 *
 * Aproximación honesta, no un simulador RF: espacio libre (FSPL) + difracción
 * de UN filo equivalente (Bullington) + curvatura terrestre
 * con k=4/3, sobre el DEM que ya usa el mapa 3D. NO modela vegetación,
 * edificios, lluvia ni multitrayecto: «Pérdida extra del entorno» es el
 * cajón donde el operador puede meter su estimación.
 *
 * Método: barrido polar. Para cada radial se avanza desde el transmisor
 * recordando la pendiente máxima del terreno visto; si el receptor queda por
 * debajo de esa pendiente, está obstruido y paga la difracción del filo
 * dominante. Coste O(radiales × pasos).
 */
import { DEM } from "../map3d/map3dConfig";
import { loadTile, worldPixel } from "../map3d/elevation";
import type { LngLat } from "../map3d/traceGeometry";

const EARTH_R = 6_371_000;
const K_FACTOR = 4 / 3;
const LIGHT = 299_792_458;
const M_PER_DEG = 111_320;
/** Pérdida empírica extra por km dentro de la zona de sombra (más allá del horizonte). */
const SHADOW_DB_PER_KM = 1;

// ── Parámetros y presets ─────────────────────────────────────────────

export interface ModemPreset {
  id: string;
  label: string;
  sf: number;
  bwKHz: number;
  /** frecuencia propia del preset (MHz), si la tiene */
  freqMHz?: number;
}

export const MODEM_PRESETS: ModemPreset[] = [
  { id: "SF_NARROW", label: "SF Narrow (SF7 · 62,5 kHz · CR 4/5)", sf: 7, bwKHz: 62.5, freqMHz: 869.618 },
  { id: "LONG_FAST", label: "Long Fast (SF11 · 250 kHz)", sf: 11, bwKHz: 250 },
  { id: "LONG_MODERATE", label: "Long Moderate (SF11 · 125 kHz)", sf: 11, bwKHz: 125 },
  { id: "LONG_SLOW", label: "Long Slow (SF12 · 125 kHz)", sf: 12, bwKHz: 125 },
  { id: "LONG_TURBO", label: "Long Turbo (SF11 · 500 kHz)", sf: 11, bwKHz: 500 },
  { id: "MEDIUM_SLOW", label: "Medium Slow (SF10 · 250 kHz)", sf: 10, bwKHz: 250 },
  { id: "MEDIUM_FAST", label: "Medium Fast (SF9 · 250 kHz)", sf: 9, bwKHz: 250 },
  { id: "SHORT_SLOW", label: "Short Slow (SF8 · 250 kHz)", sf: 8, bwKHz: 250 },
  { id: "SHORT_FAST", label: "Short Fast (SF7 · 250 kHz)", sf: 7, bwKHz: 250 },
  { id: "SHORT_TURBO", label: "Short Turbo (SF7 · 500 kHz)", sf: 7, bwKHz: 500 },
];

/** SNR mínimo demodulable de LoRa por SF (dB). */
const SNR_LIMIT: Record<number, number> = { 7: -7.5, 8: -10, 9: -12.5, 10: -15, 11: -17.5, 12: -20 };
const NOISE_FIGURE_DB = 6;

/** Sensibilidad teórica del receptor (dBm): -174 + 10·log10(BW) + NF + SNR_min. */
export function sensitivityDbm(preset: ModemPreset): number {
  return -174 + 10 * Math.log10(preset.bwKHz * 1000) + NOISE_FIGURE_DB + (SNR_LIMIT[preset.sf] ?? -17.5);
}

export interface CoverageParams {
  freqMHz: number;
  txPowerDbm: number;
  txGainDbi: number;
  /** pérdidas de cable y conectores del transmisor (dB) */
  cableLossDb: number;
  /** altura de la antena sobre el suelo (m) */
  mastM: number;
  rxGainDbi: number;
  rxHeightM: number;
  /** sensibilidad del receptor (dBm) */
  sensitivityDbm: number;
  /** margen de desvanecimiento exigido (dB) */
  fadeMarginDb: number;
  /** pérdida extra del entorno (vegetación, urbano…) (dB) */
  extraLossDb: number;
  radiusKm: number;
}

export const DEFAULT_PARAMS: CoverageParams = {
  freqMHz: MODEM_PRESETS[0].freqMHz ?? 869.525,
  txPowerDbm: 20,
  txGainDbi: 3,
  cableLossDb: 0,
  mastM: 5,
  rxGainDbi: 2,
  rxHeightM: 2,
  sensitivityDbm: Math.round(sensitivityDbm(MODEM_PRESETS[0]) * 10) / 10,
  fadeMarginDb: 10,
  extraLossDb: 0,
  radiusKm: 20,
};

export const eirpDbm = (p: CoverageParams) => p.txPowerDbm + p.txGainDbi - p.cableLossDb;

/** Pérdida en espacio libre (dB) con d en metros y f en MHz. */
export function fsplDb(distanceM: number, freqMHz: number): number {
  return 20 * Math.log10(Math.max(distanceM, 1) / 1000) + 20 * Math.log10(freqMHz) + 32.44;
}

/** Pérdida de difracción de un filo (ITU-R P.526) para el parámetro v. */
export function knifeEdgeLossDb(v: number): number {
  if (v <= -0.78) return 0;
  return 6.9 + 20 * Math.log10(Math.sqrt((v - 0.1) ** 2 + 1) + v - 0.1);
}

// ── Elevación ────────────────────────────────────────────────────────

export interface ElevationGrid {
  at(lng: number, lat: number): number | null;
  /** resolución aproximada (m/píxel) */
  resolutionM: number;
}

/** Descarga las teselas DEM que cubren un cuadrado de ±radius metros. */
export async function loadElevationGrid(center: LngLat, radiusM: number): Promise<ElevationGrid | null> {
  const lat = center[1];
  const cosLat = Math.cos((lat * Math.PI) / 180);
  const mppAtZ0 = (156_543.03 * cosLat) / (DEM.tileSize / 256);
  const spanM = radiusM * 2;
  // Mayor zoom con ≤ 8 teselas por lado (≤ ~64 descargas) y tope z12
  let z = Math.min(12, DEM.maxzoom);
  const tilesPerSide = (zz: number) => spanM / ((DEM.tileSize * mppAtZ0) / 2 ** zz) + 1;
  while (z > 6 && tilesPerSide(z) > 8) z--;
  const n = 2 ** z;
  const dLat = radiusM / M_PER_DEG;
  const dLng = radiusM / (M_PER_DEG * cosLat);
  const [x0, y0] = worldPixel(center[0] - dLng, lat + dLat, z);
  const [x1, y1] = worldPixel(center[0] + dLng, lat - dLat, z);
  const tiles = new Map<string, ImageData | null>();
  const jobs: Promise<void>[] = [];
  for (let ty = Math.floor(y0); ty <= Math.floor(y1); ty++) {
    for (let tx = Math.floor(x0); tx <= Math.floor(x1); tx++) {
      jobs.push(
        (async () => {
          const wrapped = ((tx % n) + n) % n;
          tiles.set(`${tx}/${ty}`, ty < 0 || ty >= n ? null : await loadTile(z, wrapped, ty));
        })(),
      );
    }
  }
  await Promise.all(jobs);
  if (![...tiles.values()].some(Boolean)) return null;
  return {
    resolutionM: mppAtZ0 / n,
    at(lng, la) {
      const [wx, wy] = worldPixel(lng, la, z);
      const tx = Math.floor(wx);
      const ty = Math.floor(wy);
      const img = tiles.get(`${tx}/${ty}`);
      if (!img) return null;
      const px = Math.min(img.width - 1, Math.floor((wx - tx) * img.width));
      const py = Math.min(img.height - 1, Math.floor((wy - ty) * img.height));
      const o = (py * img.width + px) * 4;
      return img.data[o] * 256 + img.data[o + 1] + img.data[o + 2] / 256 - 32768;
    },
  };
}

// ── Cálculo ──────────────────────────────────────────────────────────

export interface CoverageResult {
  center: LngLat;
  params: CoverageParams;
  rays: number;
  steps: number;
  stepM: number;
  /** margen (dB) por [radial·steps + paso]; NaN = sin dato de terreno */
  margin: Float32Array;
  /** elevación del terreno bajo el transmisor (m) */
  groundM: number;
  eirpDbm: number;
  /** área con margen ≥ 0 (km²) */
  areaKm2: number;
  /** alcance (m) por radial: último paso con margen ≥ 0 */
  reachM: Float32Array;
  maxReachM: number;
  maxReachBearing: number;
  meanReachM: number;
}

export function computeCoverage(center: LngLat, grid: ElevationGrid, p: CoverageParams): CoverageResult | null {
  const ground = grid.at(center[0], center[1]);
  if (ground == null) return null;
  const radiusM = p.radiusKm * 1000;
  const stepM = Math.max(grid.resolutionM, radiusM / 400);
  const steps = Math.max(2, Math.round(radiusM / stepM));
  const rays = Math.max(360, Math.min(1080, Math.round((2 * Math.PI * radiusM) / (stepM * 2))));
  const cosLat = Math.cos((center[1] * Math.PI) / 180);
  const lambda = LIGHT / (p.freqMHz * 1e6);
  const eirp = p.txPowerDbm + p.txGainDbi - p.cableLossDb;
  const hTx = ground + p.mastM;
  const margin = new Float32Array(rays * steps).fill(NaN);
  const reachM = new Float32Array(rays);
  let areaM2 = 0;
  const dTheta = (2 * Math.PI) / rays;
  const terrainZ = new Float32Array(steps + 1);

  for (let r = 0; r < rays; r++) {
    const brg = (r / rays) * 2 * Math.PI; // 0 = norte, sentido horario
    const sinB = Math.sin(brg);
    const cosB = Math.cos(brg);
    let maxSlope = -Infinity;
    terrainZ.fill(NaN);
    let shadowFromD = -1; // distancia a la que empieza la sombra de esta radial
    for (let i = 1; i <= steps; i++) {
      const d = i * stepM;
      const lng = center[0] + (d * sinB) / (M_PER_DEG * cosLat);
      const lat = center[1] + (d * cosB) / M_PER_DEG;
      const g = grid.at(lng, lat);
      if (g == null) continue;
      const drop = (d * d) / (2 * K_FACTOR * EARTH_R);
      const rxZ = g + p.rxHeightM - drop;
      const slopeRx = (rxZ - hTx) / d;
      let loss = fsplDb(d, p.freqMHz);
      if (maxSlope > slopeRx) {
        // Obstruido: filo equivalente de Bullington = cruce del horizonte visto
        // desde el emisor con el visto desde el receptor (mirando hacia atrás).
        // Con solo el obstáculo dominante, más allá del horizonte el filo sería
        // siempre el terreno pegado al receptor y la pérdida se quedaría en ~6 dB.
        let sR = -Infinity;
        for (let j = i - 1; j >= 1; j--) {
          const zj = terrainZ[j];
          if (Number.isNaN(zj)) continue;
          const s = (zj - rxZ) / (d - j * stepM);
          if (s > sR) sR = s;
        }
        const x = (rxZ - hTx + sR * d) / (maxSlope + sR);
        if (Number.isFinite(x) && x > 0 && x < d) {
          const h = (maxSlope - slopeRx) * x;
          const v = h * Math.sqrt((2 * d) / (lambda * x * (d - x)));
          loss += knifeEdgeLossDb(v);
        }
        // Un solo filo subestima la sombra profunda (Tierra curva): el empírico
        // de 1 dB por km dentro de la sombra evita alcances irreales más allá del horizonte.
        if (shadowFromD < 0) shadowFromD = d;
        loss += (SHADOW_DB_PER_KM * (d - shadowFromD)) / 1000;
      }
      const rssi = eirp - loss - p.extraLossDb + p.rxGainDbi;
      const m = rssi - p.sensitivityDbm - p.fadeMarginDb;
      margin[r * steps + (i - 1)] = m;
      if (m >= 0) {
        reachM[r] = d;
        areaM2 += 0.5 * dTheta * ((d + stepM / 2) ** 2 - (d - stepM / 2) ** 2);
      }
      // el terreno (sin altura de receptor) alimenta la pendiente máxima
      terrainZ[i] = g - drop;
      const slopeT = (terrainZ[i] - hTx) / d;
      if (slopeT > maxSlope) maxSlope = slopeT;
    }
  }
  let maxReach = 0;
  let maxIdx = 0;
  let sum = 0;
  for (let r = 0; r < rays; r++) {
    sum += reachM[r];
    if (reachM[r] > maxReach) {
      maxReach = reachM[r];
      maxIdx = r;
    }
  }
  return {
    center,
    params: p,
    rays,
    steps,
    stepM,
    margin,
    groundM: ground,
    eirpDbm: eirp,
    areaKm2: areaM2 / 1e6,
    reachM,
    maxReachM: maxReach,
    maxReachBearing: (maxIdx / rays) * 360,
    meanReachM: sum / rays,
  };
}

/** Margen (dB) en un punto, o null si cae fuera del radio / sin dato. */
export function marginAt(res: CoverageResult, lng: number, lat: number): { margin: number; distanceM: number; bearing: number } | null {
  const cosLat = Math.cos((res.center[1] * Math.PI) / 180);
  const dx = (lng - res.center[0]) * M_PER_DEG * cosLat;
  const dy = (lat - res.center[1]) * M_PER_DEG;
  const d = Math.hypot(dx, dy);
  const i = Math.round(d / res.stepM);
  if (i < 1 || i > res.steps) return null;
  const bearing = ((Math.atan2(dx, dy) * 180) / Math.PI + 360) % 360;
  const r = Math.round((bearing / 360) * res.rays) % res.rays;
  const m = res.margin[r * res.steps + (i - 1)];
  return Number.isNaN(m) ? null : { margin: m, distanceM: d, bearing };
}

// ── Pintado ──────────────────────────────────────────────────────────

/** Bandas de margen: más margen = más brillo (rampa secuencial ámbar → verde → turquesa). */
export const MARGIN_BANDS: { min: number; rgba: [number, number, number, number]; label: string }[] = [
  { min: 0, rgba: [229, 160, 60, 150], label: "0–6 dB · límite" },
  { min: 6, rgba: [190, 200, 70, 160], label: "6–15 dB · justo" },
  { min: 15, rgba: [70, 190, 110, 170], label: "15–25 dB · bueno" },
  { min: 25, rgba: [60, 210, 210, 185], label: "> 25 dB · holgado" },
];

export function bandOf(margin: number) {
  if (margin < 0) return null;
  let band = MARGIN_BANDS[0];
  for (const b of MARGIN_BANDS) if (margin >= b.min) band = b;
  return band;
}

export interface PaintedOverlay {
  canvas: HTMLCanvasElement;
  /** esquinas [NO, NE, SE, SO] en lng/lat para una fuente `image` de MapLibre */
  coordinates: [LngLat, LngLat, LngLat, LngLat];
}

const PX = 768;

/** Pinta el resultado polar en un lienzo alineado con Web Mercator. */
export function paintOverlay(res: CoverageResult): PaintedOverlay {
  const R = res.params.radiusKm * 1000;
  const cosLat = Math.cos((res.center[1] * Math.PI) / 180);
  const dLat = R / M_PER_DEG;
  const dLng = R / (M_PER_DEG * cosLat);
  const w0 = worldPixel(res.center[0] - dLng, res.center[1] + dLat, 0);
  const w1 = worldPixel(res.center[0] + dLng, res.center[1] - dLat, 0);
  const canvas = document.createElement("canvas");
  canvas.width = PX;
  canvas.height = PX;
  const ctx = canvas.getContext("2d")!;
  const img = ctx.createImageData(PX, PX);
  for (let py = 0; py < PX; py++) {
    const wy = w0[1] + ((w1[1] - w0[1]) * (py + 0.5)) / PX;
    const lat = (Math.atan(Math.sinh(Math.PI * (1 - 2 * wy))) * 180) / Math.PI;
    for (let px = 0; px < PX; px++) {
      const wx = w0[0] + ((w1[0] - w0[0]) * (px + 0.5)) / PX;
      const lng = wx * 360 - 180;
      const hit = marginAt(res, lng, lat);
      if (!hit) continue;
      const band = bandOf(hit.margin);
      if (!band) continue;
      const o = (py * PX + px) * 4;
      img.data[o] = band.rgba[0];
      img.data[o + 1] = band.rgba[1];
      img.data[o + 2] = band.rgba[2];
      img.data[o + 3] = band.rgba[3];
    }
  }
  ctx.putImageData(img, 0, 0);
  return {
    canvas,
    coordinates: [
      [res.center[0] - dLng, res.center[1] + dLat],
      [res.center[0] + dLng, res.center[1] + dLat],
      [res.center[0] + dLng, res.center[1] - dLat],
      [res.center[0] - dLng, res.center[1] - dLat],
    ],
  };
}

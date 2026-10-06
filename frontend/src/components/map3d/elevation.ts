/**
 * Perfil topográfico entre dos puntos y análisis de línea de visión (LOS).
 *
 * La elevación se lee de las MISMAS teselas DEM que dibuja el mapa (`DEM`,
 * formato Terrarium) pero decodificándolas aquí, no consultando el terreno del
 * mapa: así el perfil no depende de qué parte esté en pantalla ni de que las
 * teselas ya se hayan descargado para la vista.
 */
import { DEM } from "./map3dConfig";
import { distanceM, type LngLat } from "./traceGeometry";

const EARTH_R = 6_371_000;
/** Factor k de refracción estándar (radio efectivo 4/3). */
const K_FACTOR = 4 / 3;
const LIGHT = 299_792_458;
/** Zoom máximo del muestreo: más detalle no compensa el nº de teselas en trayectos largos. */
const MAX_SAMPLE_ZOOM = 12;

const tileCache = new Map<string, Promise<ImageData | null>>();

function tileUrl(z: number, x: number, y: number): string {
  return DEM.tiles[0].replace("{z}", String(z)).replace("{x}", String(x)).replace("{y}", String(y));
}

export function loadTile(z: number, x: number, y: number): Promise<ImageData | null> {
  const key = `${z}/${x}/${y}`;
  let p = tileCache.get(key);
  if (!p) {
    p = (async () => {
      try {
        const res = await fetch(tileUrl(z, x, y));
        if (!res.ok) return null;
        const bmp = await createImageBitmap(await res.blob(), {
          colorSpaceConversion: "none",
          premultiplyAlpha: "none",
        });
        const canvas = document.createElement("canvas");
        canvas.width = bmp.width;
        canvas.height = bmp.height;
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        if (!ctx) return null;
        ctx.drawImage(bmp, 0, 0);
        return ctx.getImageData(0, 0, bmp.width, bmp.height);
      } catch {
        return null;
      }
    })();
    // Un fallo no se queda cacheado para siempre
    p.then((v) => v === null && tileCache.delete(key));
    tileCache.set(key, p);
  }
  return p;
}

/** Coordenadas de teselas (fraccionarias) de un punto a un zoom. */
export function worldPixel(lng: number, lat: number, z: number): [number, number] {
  const n = 2 ** z;
  const x = ((lng + 180) / 360) * n;
  const s = Math.sin((lat * Math.PI) / 180);
  const y = (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n;
  return [x, y];
}

export interface ProfileSample {
  /** distancia desde A, en metros */
  d: number;
  lngLat: LngLat;
  /** elevación del terreno (m); null si la tesela no pudo leerse */
  ground: number | null;
}

/** Muestrea el terreno a lo largo de la recta A→B. Devuelve null si no hay datos. */
export async function sampleProfile(a: LngLat, b: LngLat): Promise<ProfileSample[] | null> {
  const total = Math.max(1, distanceM(a, b));
  const count = Math.min(300, Math.max(60, Math.round(total / 60)));
  // Zoom cuya resolución (m/píxel) acompaña al espaciado de las muestras
  const midLat = (a[1] + b[1]) / 2;
  const spacing = total / count;
  const mppAtZ0 = (156_543.03 * Math.cos((midLat * Math.PI) / 180)) / (DEM.tileSize / 256);
  const z = Math.max(6, Math.min(MAX_SAMPLE_ZOOM, DEM.maxzoom, Math.ceil(Math.log2(mppAtZ0 / spacing))));
  const n = 2 ** z;

  const samples: ProfileSample[] = [];
  const need = new Map<string, [number, number]>();
  for (let i = 0; i <= count; i++) {
    const f = i / count;
    const lngLat: LngLat = [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
    samples.push({ d: total * f, lngLat, ground: null });
    const [wx, wy] = worldPixel(lngLat[0], lngLat[1], z);
    const tx = Math.floor(wx);
    const ty = Math.floor(wy);
    need.set(`${tx}/${ty}`, [tx, ty]);
  }
  const tiles = new Map<string, ImageData | null>();
  await Promise.all(
    [...need].map(async ([k, [tx, ty]]) => {
      tiles.set(k, ty < 0 || ty >= n ? null : await loadTile(z, ((tx % n) + n) % n, ty));
    }),
  );
  let any = false;
  for (const s of samples) {
    const [wx, wy] = worldPixel(s.lngLat[0], s.lngLat[1], z);
    const tx = Math.floor(wx);
    const ty = Math.floor(wy);
    const img = tiles.get(`${tx}/${ty}`);
    if (!img) continue;
    const px = Math.min(img.width - 1, Math.floor((wx - tx) * img.width));
    const py = Math.min(img.height - 1, Math.floor((wy - ty) * img.height));
    const o = (py * img.width + px) * 4;
    // Terrarium: metros = R*256 + G + B/256 - 32768
    s.ground = img.data[o] * 256 + img.data[o + 1] + img.data[o + 2] / 256 - 32768;
    any = true;
  }
  return any ? samples : null;
}

export interface LosPoint {
  d: number;
  /** terreno + abombamiento de la Tierra (m) */
  terrain: number;
  /** altura de la línea recta entre antenas (m) */
  los: number;
  /** radio de la 1.ª zona de Fresnel en ese punto (m) */
  fresnel: number;
  /** holgura LOS - terreno (m): negativa = obstruido */
  clearance: number;
}

export interface LosResult {
  points: LosPoint[];
  distanceM: number;
  /** punto con menos holgura frente a la línea recta */
  worst: LosPoint;
  /** peor holgura respecto al 60 % de Fresnel (criterio habitual de enlace) */
  worstFresnel: LosPoint;
  clear: boolean;
  fresnelClear: boolean;
  /** elevaciones de las antenas (terreno + mástil), m */
  heightA: number;
  heightB: number;
  /** sin datos de terreno en parte del trayecto */
  gaps: number;
  /** frecuencia usada (MHz) */
  freqMHz: number;
  /** pérdida en espacio libre, dB: 20·log10(d_km) + 20·log10(f_MHz) + 32,44 */
  fsplDb: number;
  /** radio de la 1.ª zona de Fresnel en el punto medio del trayecto (m) */
  fresnelMidM: number;
}

/** Pérdida de trayecto en espacio libre (FSPL) en dB, con d en metros y f en MHz. */
export function fspl(distanceM: number, freqMHz: number): number {
  return 20 * Math.log10(Math.max(distanceM, 1) / 1000) + 20 * Math.log10(freqMHz) + 32.44;
}

export function analyzeLos(
  samples: ProfileSample[],
  opts: { mastA: number; mastB: number; freqMHz: number },
): LosResult | null {
  const known = samples.filter((s) => s.ground != null);
  if (known.length < 2) return null;
  const D = samples[samples.length - 1].d;
  const gA = known[0].ground!;
  const gB = known[known.length - 1].ground!;
  const hA = gA + opts.mastA;
  const hB = gB + opts.mastB;
  const lambda = LIGHT / (opts.freqMHz * 1e6);
  const points: LosPoint[] = known.map((s) => {
    const bulge = (s.d * (D - s.d)) / (2 * K_FACTOR * EARTH_R);
    const los = hA + ((hB - hA) * s.d) / D;
    const fresnel = Math.sqrt((lambda * s.d * (D - s.d)) / D);
    const terrain = s.ground! + bulge;
    return { d: s.d, terrain, los, fresnel, clearance: los - terrain };
  });
  const inner = points.length > 2 ? points.slice(1, -1) : points;
  const worst = inner.reduce((m, p) => (p.clearance < m.clearance ? p : m), inner[0]);
  const worstFresnel = inner.reduce(
    (m, p) => (p.clearance - 0.6 * p.fresnel < m.clearance - 0.6 * m.fresnel ? p : m),
    inner[0],
  );
  return {
    points,
    distanceM: D,
    worst,
    worstFresnel,
    clear: worst.clearance > 0,
    fresnelClear: worstFresnel.clearance - 0.6 * worstFresnel.fresnel > 0,
    heightA: hA,
    heightB: hB,
    gaps: samples.length - known.length,
    freqMHz: opts.freqMHz,
    fsplDb: fspl(D, opts.freqMHz),
    fresnelMidM: Math.sqrt((lambda * (D / 2) * (D / 2)) / D),
  };
}

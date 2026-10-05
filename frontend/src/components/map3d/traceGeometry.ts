/**
 * Geometría pura del mapa 3D de una traza (sin MapLibre ni React, testeable).
 *
 * MapLibre no dibuja líneas con altura, así que los arcos se construyen como
 * una cinta de pequeños prismas (fill-extrusion): cada tramo del arco es un
 * cuadrilátero con `base`/`height` distintos, lo que da un tubo curvado en el
 * aire que además respeta el relieve. Todo en metros sobre el suelo del nodo.
 */
import type { TraceOut } from "../../api/client";

export type LngLat = [number, number];

const UNKNOWN_NODE = "!ffffffff";
const M_PER_DEG_LAT = 111_320;

export interface TraceHop {
  from: string;
  to: string;
  snr: number | null;
  /** 0 = ida (origen → destino), 1 = vuelta */
  leg: 0 | 1;
  /** posición global dentro de la animación (ida y luego vuelta) */
  seq: number;
}

/** Tramos dirigidos de la traza, ida primero y vuelta después. */
export function hopsOf(trace: TraceOut): TraceHop[] {
  const out: TraceHop[] = [];
  const leg = (path: string[], snrs: (number | null)[], l: 0 | 1) => {
    for (let i = 0; i < path.length - 1; i++) {
      const [from, to] = [path[i], path[i + 1]];
      if (from === UNKNOWN_NODE || to === UNKNOWN_NODE || from === to) continue;
      out.push({ from, to, snr: snrs[i] ?? null, leg: l, seq: out.length });
    }
  };
  leg([trace.origin_id, ...trace.route, trace.target_id], trace.snr_towards, 0);
  if (trace.route_back.length > 0 || trace.snr_back.length > 0) {
    leg([trace.target_id, ...trace.route_back, trace.origin_id], trace.snr_back, 1);
  }
  return out;
}

/** Nodos distintos de la traza, en orden de aparición (los únicos que se dibujan). */
export function nodesOf(hops: TraceHop[]): string[] {
  return [...new Set(hops.flatMap((h) => [h.from, h.to]))];
}

/** Color del enlace según su SNR (mismos umbrales que TracerouteDialog). */
export function snrColor(snr: number | null): string {
  if (snr == null) return "#8a93a3";
  if (snr >= 5) return "#2ea06a";
  if (snr >= 0) return "#7bc47f";
  if (snr >= -7) return "#d9a03c";
  return "#e5484d";
}

const toRad = (d: number) => (d * Math.PI) / 180;

export function distanceM(a: LngLat, b: LngLat): number {
  const dLat = toRad(b[1] - a[1]);
  const dLng = toRad(b[0] - a[0]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a[1])) * Math.cos(toRad(b[1])) * Math.sin(dLng / 2) ** 2;
  return 2 * 6_371_000 * Math.asin(Math.sqrt(h));
}

/** Desplaza un punto `dx` metros al este y `dy` al norte. */
function offset(p: LngLat, dx: number, dy: number): LngLat {
  return [p[0] + dx / (M_PER_DEG_LAT * Math.cos(toRad(p[1]))), p[1] + dy / M_PER_DEG_LAT];
}

/** Polígono regular (aprox. círculo) de radio `r` metros — base de los pilares. */
export function disc(center: LngLat, r: number, sides = 14): LngLat[] {
  const ring: LngLat[] = [];
  for (let i = 0; i < sides; i++) {
    const ang = (2 * Math.PI * i) / sides;
    ring.push(offset(center, r * Math.cos(ang), r * Math.sin(ang)));
  }
  ring.push(ring[0]);
  return ring;
}

export interface Ribbon {
  /** índice global creciente a lo largo de toda la animación */
  order: number;
  hop: number;
  leg: 0 | 1;
  ring: LngLat[];
  base: number;
  height: number;
  color: string;
}

/**
 * Cinta de prismas para un tramo a→b. El arco nace en lo alto de los pilares
 * (`pillarH`), sube `peak` metros hacia el centro y vuelve a bajar. `side`
 * separa lateralmente ida y vuelta para que no se solapen.
 */
export function buildArc(
  a: LngLat,
  b: LngLat,
  o: { steps: number; pillarH: number; peak: number; halfW: number; side: number; hop: number; leg: 0 | 1; color: string; orderStart: number },
): Ribbon[] {
  const { steps, pillarH, peak, halfW } = o;
  // vector perpendicular en metros (este/norte) para el desplazamiento lateral
  const dxm = (b[0] - a[0]) * M_PER_DEG_LAT * Math.cos(toRad(a[1]));
  const dym = (b[1] - a[1]) * M_PER_DEG_LAT;
  const len = Math.hypot(dxm, dym) || 1;
  const nx = -dym / len;
  const ny = dxm / len;
  const pts: { p: LngLat; z: number }[] = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const base: LngLat = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
    const lift = Math.sin(Math.PI * t); // 0 en los extremos, 1 en el centro
    pts.push({
      p: offset(base, nx * o.side * lift, ny * o.side * lift),
      z: pillarH + peak * lift,
    });
  }
  const ribbons: Ribbon[] = [];
  for (let i = 0; i < steps; i++) {
    const [p0, p1] = [pts[i].p, pts[i + 1].p];
    const sx = (p1[0] - p0[0]) * M_PER_DEG_LAT * Math.cos(toRad(p0[1]));
    const sy = (p1[1] - p0[1]) * M_PER_DEG_LAT;
    const sl = Math.hypot(sx, sy) || 1;
    const [px, py] = [(-sy / sl) * halfW, (sx / sl) * halfW];
    const ring: LngLat[] = [offset(p0, px, py), offset(p1, px, py), offset(p1, -px, -py), offset(p0, -px, -py)];
    ring.push(ring[0]);
    const zMid = (pts[i].z + pts[i + 1].z) / 2;
    ribbons.push({
      order: o.orderStart + i,
      hop: o.hop,
      leg: o.leg,
      ring,
      base: Math.max(0, zMid - halfW),
      height: zMid + halfW,
      color: o.color,
    });
  }
  return ribbons;
}

/** Posición (lng/lat/z) de la "cabeza" del pulso para la cinta `order`. */
export function ribbonCenter(r: Ribbon): { lngLat: LngLat; z: number } {
  const xs = r.ring.slice(0, 4);
  return {
    lngLat: [xs.reduce((s, p) => s + p[0], 0) / 4, xs.reduce((s, p) => s + p[1], 0) / 4],
    z: (r.base + r.height) / 2,
  };
}

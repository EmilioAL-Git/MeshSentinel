/**
 * Utilidades geométricas puras para las capas del mapa (Centro de
 * Operaciones): sin dependencias externas (el proyecto no tiene turf.js).
 */

/** Envolvente convexa (monotone chain) sobre puntos [lat, lng].
 * Aproximación local válida a escala de una malla LoRa (no corrige la
 * proyección Mercator) — suficiente para "cobertura aproximada", nunca un
 * modelo de propagación RF real (ver CoverageLayer). */
export function convexHull(points: [number, number][]): [number, number][] {
  const pts = Array.from(new Set(points.map((p) => p.join(","))))
    .map((s) => s.split(",").map(Number) as [number, number])
    .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (pts.length < 3) return pts;

  const cross = (o: [number, number], a: [number, number], b: [number, number]) =>
    (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);

  const lower: [number, number][] = [];
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) {
      lower.pop();
    }
    lower.push(p);
  }
  const upper: [number, number][] = [];
  for (let i = pts.length - 1; i >= 0; i--) {
    const p = pts[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) {
      upper.pop();
    }
    upper.push(p);
  }
  upper.pop();
  lower.pop();
  return [...lower, ...upper];
}

/** Distancia aproximada en metros entre dos puntos [lat, lng] (haversine). */
export function haversineMeters(a: [number, number], b: [number, number]): number {
  const R = 6371000;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b[0] - a[0]);
  const dLng = toRad(b[1] - a[1]);
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a[0])) * Math.cos(toRad(b[0])) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

/** Color por SNR (dB), mismo criterio que LinksLayer/MapView "Calidad". */
export function snrColor(snr: number | null): string {
  if (snr == null) return "var(--text-dim)";
  if (snr < -12) return "var(--crit)";
  if (snr < 0) return "var(--warn)";
  return "var(--ok)";
}

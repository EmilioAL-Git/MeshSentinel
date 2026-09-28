/**
 * Insignia de nodo JenTastic-Nexus: gato en pixel-art derivado del logo del
 * propio firmware (pantalla OLED "EU_868 / JenTastic-nexus", cian sobre
 * negro) — pedido explícito del usuario a partir de esa captura. Un solo
 * icono SVG reutilizado en Flota/Inspector/Mapa, nunca repintado a mano en
 * cada sitio: la geometría vive en UN sitio (`NEXUS_CAT_RECTS`) y de ahí
 * salen tanto el componente React (Flota/Inspector) como el marcado HTML
 * crudo que necesita Leaflet (`nexusCatMarkup`, los `L.divIcon` del mapa no
 * pueden montar JSX).
 */

type Fill = "accent" | "chassis";

export const NEXUS_CAT_RECTS: readonly [x: number, y: number, w: number, h: number, fill: Fill][] = [
  // orejas
  [2, 0, 2, 2, "accent"],
  [7, 0, 2, 2, "accent"],
  // cabeza
  [1, 2, 9, 1, "accent"],
  // cuerpo
  [0, 3, 11, 4, "accent"],
  // ojo (recorte)
  [2, 4, 1, 1, "chassis"],
  // patas
  [1, 7, 2, 2, "accent"],
  [4, 7, 2, 2, "accent"],
  [7, 7, 2, 2, "accent"],
  // cola, enroscada hacia arriba
  [11, 5, 2, 1, "accent"],
  [12, 3, 2, 2, "accent"],
  [13, 1, 2, 2, "accent"],
  [12, 0, 2, 1, "accent"],
];

const FILL_VAR: Record<Fill, string> = { accent: "var(--accent)", chassis: "var(--chassis)" };

export function NexusCatIcon({
  size = 14,
  title = "Nodo JenTastic-Nexus",
}: {
  size?: number;
  title?: string;
}) {
  return (
    <svg
      width={size}
      height={size * (10 / 16)}
      viewBox="0 0 16 10"
      shapeRendering="crispEdges"
      role="img"
      aria-label={title}
      style={{ display: "inline-block", verticalAlign: "middle" }}
    >
      <title>{title}</title>
      {NEXUS_CAT_RECTS.map(([x, y, w, h, fill], i) => (
        <rect key={i} x={x} y={y} width={w} height={h} fill={FILL_VAR[fill]} />
      ))}
    </svg>
  );
}

/** Marcado HTML crudo (sin React) para `L.divIcon` — mismos rects que arriba. */
export function nexusCatMarkup(size = 14): string {
  const h = size * (10 / 16);
  const rects = NEXUS_CAT_RECTS.map(
    ([x, y, w, hh, fill]) => `<rect x="${x}" y="${y}" width="${w}" height="${hh}" fill="${FILL_VAR[fill]}"/>`,
  ).join("");
  return (
    `<svg width="${size}" height="${h}" viewBox="0 0 16 10" shape-rendering="crispEdges" ` +
    `role="img" aria-label="Nodo JenTastic-Nexus">${rects}</svg>`
  );
}

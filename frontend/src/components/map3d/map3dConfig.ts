/**
 * Fuentes del mapa 3D. Todas GRATUITAS y SIN clave:
 *  - Estilo vectorial oscuro: CARTO Dark Matter (datos © OpenStreetMap, © CARTO).
 *    Uso gratuito no comercial con atribución.
 *  - Relieve: "Terrain Tiles" de AWS Open Data (formato Terrarium, dominio
 *    público/atribución a las fuentes SRTM, etc.).
 * Están aquí, y solo aquí, para poder cambiarlas por un servidor propio
 * (PMTiles / DEM autoalojado) sin tocar la vista. Sin red, la vista cae a un
 * fondo plano sin relieve (ver `FALLBACK_STYLE`).
 */
import type { StyleSpecification } from "maplibre-gl";

export const BASE_STYLE_URL = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

/**
 * Elevación: Mapterhorn (gratis, sin clave, formato Terrarium, teselas de 512 px
 * y hasta zoom 17, mezcla de las mejores fuentes abiertas por zona). Antes se usaba
 * AWS Terrain Tiles, que se queda en zoom 15 (~30 m reales en España) y se veía
 * poco detallado; sigue siendo la reserva (cambiar `DEM`).
 */
export const DEM_MAPTERHORN = {
  tiles: ["https://tiles.mapterhorn.com/{z}/{x}/{y}.webp"],
  tileSize: 512,
  maxzoom: 17,
  attribution: '<a href="https://mapterhorn.com/attribution" target="_blank" rel="noreferrer">© Mapterhorn</a>',
} as const;

export const DEM_AWS = {
  tiles: ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"],
  tileSize: 256,
  maxzoom: 15,
  attribution:
    'Relieve: <a href="https://registry.opendata.aws/terrain-tiles/" target="_blank" rel="noreferrer">AWS Terrain Tiles</a>',
} as const;

/** Fuente de elevación en uso. */
export const DEM = DEM_MAPTERHORN;

/**
 * Imagen de satélite: Sentinel-2 cloudless (EOX). Gratis y sin clave para uso NO
 * comercial (CC BY-NC 4.0); resolución ~10 m, se desenfoca por encima de z13.
 */
export const SATELLITE_TILES = ["https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2021_3857/default/g/{z}/{y}/{x}.jpg"];
export const SATELLITE_ATTRIBUTION =
  '<a href="https://s2maps.eu" target="_blank" rel="noreferrer">Sentinel-2 cloudless</a> © <a href="https://eox.at" target="_blank" rel="noreferrer">EOX IT Services</a> (contiene datos Copernicus Sentinel modificados 2021)';

export type BaseMode = "dark" | "satellite" | "relief";

/** Exageraciones verticales ofrecidas (1 = relieve real). */
export const EXAGGERATIONS = [1, 2, 3, 5] as const;

/** Fondo mínimo cuando el estilo remoto no carga (sin internet). */
export const FALLBACK_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#11151d" } }],
};

/** Exageración vertical del relieve (1 = real). Las mallas suelen ser poco montañosas. */
export const TERRAIN_EXAGGERATION = 2;

/**
 * Rampa hipsométrica del modo «Relieve»: degradado verde → ocre → marrón → blanco
 * con BANDAS cada 100 m (cada banda par un 10 % más oscura). En mesetas casi
 * llanas, donde un degradado suave sería de un solo color, las bandas dejan
 * ver la forma del terreno como curvas de nivel.
 */
export function reliefColorStops(): (number | string)[] {
  const base: [number, [number, number, number]][] = [
    [0, [34, 87, 72]],
    [300, [54, 120, 80]],
    [600, [120, 150, 80]],
    [900, [176, 160, 92]],
    [1200, [190, 140, 96]],
    [1600, [168, 120, 100]],
    [2200, [200, 190, 185]],
    [3000, [245, 246, 250]],
  ];
  const at = (e: number): [number, number, number] => {
    for (let i = 0; i < base.length - 1; i++) {
      const [e0, c0] = base[i];
      const [e1, c1] = base[i + 1];
      if (e <= e1) return c0.map((v, k) => v + ((c1[k] - v) * (e - e0)) / (e1 - e0)) as [number, number, number];
    }
    return base[base.length - 1][1];
  };
  const stops: (number | string)[] = [];
  for (let e = 0; e <= 3200; e += 100) {
    const f = (e / 100) % 2 === 0 ? 1 : 0.9;
    const [r, g, b] = at(e).map((v) => Math.round(v * f));
    const color = `rgb(${r},${g},${b})`;
    if (e > 0) stops.push(e - 0.5, color); // escalón brusco entre bandas
    stops.push(e, color);
  }
  return stops;
}

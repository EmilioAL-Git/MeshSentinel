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

export const TERRAIN_TILES = ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"];
export const TERRAIN_ATTRIBUTION =
  'Relieve: <a href="https://registry.opendata.aws/terrain-tiles/" target="_blank" rel="noreferrer">AWS Terrain Tiles</a>';

/** Fondo mínimo cuando el estilo remoto no carga (sin internet). */
export const FALLBACK_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#11151d" } }],
};

/** Exageración vertical del relieve (1 = real). Las mallas suelen ser poco montañosas. */
export const TERRAIN_EXAGGERATION = 1.6;

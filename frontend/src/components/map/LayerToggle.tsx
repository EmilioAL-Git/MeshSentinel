import { t } from "../../tokens";

/**
 * Barra de capas del mapa (Fase B.1, v0.9): togglea qué categorías de
 * marcadores se muestran (reutiliza `classify.ts`), el modo de coloreado
 * (estado/calidad/redundancia — mismos datos ya presentes en `nodeIcon`) y
 * la capa "Enlaces" (Fase B.2). Estado persistido fuera de este componente
 * (`usePersistedState` en `MapView.tsx`), este solo es presentación.
 */

export type MapColorMode = "status" | "quality" | "redundancy";

export interface MapLayerState {
  showInfra: boolean;
  showGateways: boolean;
  showUsers: boolean;
  showFixed: boolean;
  showFavoritesOnly: boolean;
  showLinks: boolean;
  /** Enlaces nodo↔nodo reales (NEIGHBORINFO_APP) — topología de malla. */
  showNeighbors: boolean;
  /** Historial GPS del nodo en Focus/seleccionado. */
  showTraces: boolean;
  /** Rutas de traceroute recientes (activity_log). */
  showRoutes: boolean;
  /** Área aproximada por pasarela derivada de sus enlaces activos. */
  showCoverage: boolean;
  colorMode: MapColorMode;
}

export const DEFAULT_MAP_LAYERS: MapLayerState = {
  showInfra: true,
  showGateways: true,
  showUsers: true,
  showFixed: true,
  showFavoritesOnly: false,
  showLinks: false,
  showNeighbors: false,
  showTraces: false,
  showRoutes: false,
  showCoverage: false,
  colorMode: "status",
};

const chipBtn = (active: boolean): React.CSSProperties => ({
  cursor: "pointer",
  fontSize: 11,
  padding: "0.15rem 0.5rem",
  borderRadius: 4,
  border: `1px solid ${active ? t.accent : t.border}`,
  background: active ? "color-mix(in srgb, var(--accent) 18%, transparent)" : "transparent",
  color: active ? t.accent : t.textDim,
});

export function LayerToggle({
  layers,
  onChange,
}: {
  layers: MapLayerState;
  onChange: (next: MapLayerState) => void;
}) {
  const set = <K extends keyof MapLayerState>(key: K, value: MapLayerState[K]) =>
    onChange({ ...layers, [key]: value });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem", maxWidth: 260 }}>
        <button style={chipBtn(layers.showGateways)} onClick={() => set("showGateways", !layers.showGateways)}>
          🛰 Gateways
        </button>
        <button style={chipBtn(layers.showInfra)} onClick={() => set("showInfra", !layers.showInfra)}>
          📡 Infraestructura
        </button>
        <button style={chipBtn(layers.showUsers)} onClick={() => set("showUsers", !layers.showUsers)}>
          👤 Usuarios
        </button>
        <button style={chipBtn(layers.showFixed)} onClick={() => set("showFixed", !layers.showFixed)}>
          📍 Fijos
        </button>
        <button
          style={chipBtn(layers.showFavoritesOnly)}
          onClick={() => set("showFavoritesOnly", !layers.showFavoritesOnly)}
          title="Solo favoritos, además de las categorías activas"
        >
          ★ Favoritos
        </button>
        <button style={chipBtn(layers.showLinks)} onClick={() => set("showLinks", !layers.showLinks)}>
          ╱ Enlaces
        </button>
        <button
          style={chipBtn(layers.showNeighbors)}
          onClick={() => set("showNeighbors", !layers.showNeighbors)}
          title="Enlaces nodo↔nodo reales (NeighborInfo) — requiere firmware con el módulo activado"
        >
          ⌁ Malla real
        </button>
        <button
          style={chipBtn(layers.showTraces)}
          onClick={() => set("showTraces", !layers.showTraces)}
          title="Historial GPS del nodo en Focus o del seleccionado"
        >
          〜 Traza
        </button>
        <button
          style={chipBtn(layers.showRoutes)}
          onClick={() => set("showRoutes", !layers.showRoutes)}
          title="Rutas de traceroute recientes"
        >
          🧭 Rutas
        </button>
        <button
          style={chipBtn(layers.showCoverage)}
          onClick={() => set("showCoverage", !layers.showCoverage)}
          title="Área aproximada de cobertura por pasarela (no es un modelo de propagación real)"
        >
          ◌ Cobertura
        </button>
      </div>
      <div style={{ display: "flex", gap: "0.3rem" }}>
        <button style={chipBtn(layers.colorMode === "status")} onClick={() => set("colorMode", "status")}>
          Estado
        </button>
        <button style={chipBtn(layers.colorMode === "quality")} onClick={() => set("colorMode", "quality")}>
          Calidad
        </button>
        <button style={chipBtn(layers.colorMode === "redundancy")} onClick={() => set("colorMode", "redundancy")}>
          Redundancia
        </button>
      </div>
    </div>
  );
}

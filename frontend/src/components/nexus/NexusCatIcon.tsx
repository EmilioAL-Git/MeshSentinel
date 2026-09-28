/**
 * Insignia de nodo JenTastic-Nexus: tras varias vueltas de pixel-art propio
 * que no convencieron al usuario ("ay que feooos"), se queda con el emoji
 * de gato del sistema — reconocible al instante, sin ambigüedad. Un solo
 * punto reutilizado en Flota/Inspector/Mapa: `nexusCatMarkup` es el HTML
 * crudo que necesita Leaflet (los `L.divIcon` del mapa no pueden montar JSX).
 */

export function NexusCatIcon({
  size = 18,
  title = "Nodo JenTastic-Nexus",
}: {
  size?: number;
  title?: string;
}) {
  return (
    <span
      role="img"
      aria-label={title}
      title={title}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: size * 1.5,
        height: size * 1.5,
        borderRadius: "50%",
        background: "color-mix(in srgb, var(--accent) 22%, transparent)",
        border: "1px solid color-mix(in srgb, var(--accent) 55%, transparent)",
        fontSize: size,
        lineHeight: 1,
        verticalAlign: "middle",
      }}
    >
      🐱
    </span>
  );
}

/** Marcado HTML crudo (sin React) para `L.divIcon`. */
export function nexusCatMarkup(size = 18): string {
  const box = size * 1.5;
  return (
    `<span role="img" aria-label="Nodo JenTastic-Nexus" title="Nodo JenTastic-Nexus" ` +
    `style="display:inline-flex;align-items:center;justify-content:center;width:${box}px;height:${box}px;` +
    `border-radius:50%;background:color-mix(in srgb, var(--accent) 22%, transparent);` +
    `border:1px solid color-mix(in srgb, var(--accent) 55%, transparent);font-size:${size}px;line-height:1">🐱</span>`
  );
}

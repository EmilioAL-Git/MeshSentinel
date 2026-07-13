/**
 * Tokens de diseño accesibles desde JS (v0.7, §14 del documento de diseño).
 *
 * La fuente de verdad visual es theme.css (CSS custom properties); este módulo
 * expone (a) referencias var(--…) para estilos inline de React y (b) los hex
 * crudos para los contextos que NO resuelven var(): canvas (ECharts) y las
 * cadenas HTML de los divIcon de Leaflet cuando se serializan fuera del DOM.
 * Mantener ambos archivos sincronizados.
 */

/** Referencias var(--…) — para style={} de React y HTML dentro del DOM. */
export const t = {
  bg: "var(--bg)",
  surface: "var(--surface)",
  surface2: "var(--surface-2)",
  border: "var(--border)",
  borderSubtle: "var(--border-subtle)",
  text: "var(--text)",
  textDim: "var(--text-dim)",
  textFaint: "var(--text-faint)",
  ok: "var(--ok)",
  warn: "var(--warn)",
  crit: "var(--crit)",
  accent: "var(--accent)",
  okTint: "var(--ok-tint)",
  warnTint: "var(--warn-tint)",
  critTint: "var(--crit-tint)",
  accentTint: "var(--accent-tint)",
  fontUi: "var(--font-ui)",
  fontMono: "var(--font-mono)",
  // Identidad de tipo de paquete (Registro) — nunca para estado/severidad
  catBlue: "var(--cat-blue)",
  catGreen: "var(--cat-green)",
  catOrange: "var(--cat-orange)",
  catViolet: "var(--cat-violet)",
  catAqua: "var(--cat-aqua)",
  catYellow: "var(--cat-yellow)",
  catMagenta: "var(--cat-magenta)",
} as const;

/** Hex crudos — SOLO para canvas/serializaciones sin acceso al cascade. */
export const hex = {
  bg: "#0b0e14",
  surface: "#11151d",
  border: "#232a36",
  text: "#d7dee8",
  textDim: "#8b96a5",
  ok: "#2ea06a",
  warn: "#d9a03c",
  crit: "#e5484d",
  accent: "#4c8dff",
} as const;

/**
 * Chip de estado tintado (§14.2 regla 5): texto en el color semántico sobre
 * su tinte al ~15 % con borde suave — nunca fondo sólido saturado con texto
 * blanco. `color` debe ser una referencia var(--…) de `t`.
 */
export function chipStyle(color: string): {
  background: string;
  color: string;
  border: string;
  borderRadius: number;
  padding: string;
  fontSize: string;
  whiteSpace: "nowrap";
} {
  return {
    background: `color-mix(in srgb, ${color} 15%, transparent)`,
    color,
    border: `1px solid color-mix(in srgb, ${color} 45%, transparent)`,
    borderRadius: 12,
    padding: "0.1rem 0.6rem",
    fontSize: "0.75rem",
    whiteSpace: "nowrap",
  };
}

/** Color del estado agregado de la red (semáforo, HUD, barra inferior). */
export function healthColor(status: "HEALTHY" | "WARNING" | "CRITICAL" | undefined): string {
  if (status === "HEALTHY") return t.ok;
  if (status === "WARNING") return t.warn;
  if (status === "CRITICAL") return t.crit;
  return t.textFaint;
}

/** Color de una alerta por severidad (StatusPanel, Inspector › Alertas). */
export function alertSeverityColor(severity: "CRITICAL" | "WARNING" | "INFO" | string): string {
  if (severity === "CRITICAL") return t.crit;
  if (severity === "WARNING") return t.warn;
  return t.textDim;
}

/**
 * Vista activa del Centro de Operaciones — extraído de App.tsx (URLs
 * compartibles, ADR 0026) para poder importarlo tanto desde App.tsx como
 * desde el hook de URL (`useUrlView`) sin ciclo de imports.
 */
export type View =
  | "ops"
  | "nodes"
  | "jobs"
  | "alerts"
  | "config"
  | "profiles"
  | "activity"
  | "gateways"
  | "stats"
  | "map3d"
  | "tools"
  | "traces"
  | "settings";

/**
 * Workspaces (identidad v0.8): no hay "páginas" — el riel de navegación
 * cambia de instrumento sin abandonar el chasis (cabecera + barra de
 * estado siempre presentes). El Dashboard clásico y la vista Mapa suelta
 * han muerto: el Centro de Operaciones ES el mapa y ES el dashboard.
 */
export const VIEWS: { id: View; label: string; icon: string; short?: string }[] = [
  { id: "ops", label: "Centro", icon: "◉" },
  { id: "nodes", label: "Flota", icon: "⬡" },
  { id: "jobs", label: "Trabajos", icon: "▶" },
  { id: "alerts", label: "Alertas", icon: "⚠" },
  { id: "profiles", label: "Perfiles", icon: "⧉" },
  { id: "config", label: "Admin Remota", icon: "⚙" },
  { id: "activity", label: "Registro", icon: "▤" },
  { id: "gateways", label: "Gateways", icon: "⛭" },
  { id: "stats", label: "Top", icon: "✦" },
  { id: "tools", label: "Herramientas", short: "Herram.", icon: "⚒" },
  { id: "traces", label: "Historial de trazas", icon: "⌁" },
  { id: "map3d", label: "Mapa 3D", icon: "◈" },
  // "Ajustes" agrupa Usuarios/Accesos (autenticación) junto al resto de
  // configuración — mismo criterio de visibilidad de antes (RequireAdminDep
  // en el backend para Usuarios). Icono "@wrench": sentinel que NavRail
  // traduce a un SVG propio (llave inglesa monocroma) — los emoji a color
  // como 🎚 desentonan del resto de glifos, que heredan currentColor.
  { id: "settings", label: "Ajustes", icon: "@wrench" },
];

const VIEW_IDS = new Set<string>(VIEWS.map((v) => v.id));

/**
 * Ids históricos (componentes/documentos antiguos, y ahora también rutas
 * URL antiguas tipo `/dashboard`): siguen navegando bien.
 */
export function resolveView(v: string): View {
  if (v === "operations" || v === "batches") return "jobs";
  if (v === "dashboard" || v === "map") return "ops";
  if (v === "users" || v === "login-log") return "settings";
  if (VIEW_IDS.has(v)) return v as View;
  return "ops";
}

/** Vistas que viven DENTRO de Herramientas: no tienen entrada propia en el riel. */
export const TOOL_VIEWS: readonly View[] = ["traces", "map3d", "config"];

/** Vistas con entrada propia en el riel (las herramientas cuelgan de «Herramientas»). */
export const RAIL_VIEWS = VIEWS.filter((v) => !TOOL_VIEWS.includes(v.id));

/** Entrada del riel que se ilumina para la vista actual. */
export function railActive(view: View): View {
  return TOOL_VIEWS.includes(view) ? "tools" : view;
}

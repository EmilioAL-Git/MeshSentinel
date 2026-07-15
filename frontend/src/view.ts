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
  | "users"
  | "login-log"
  | "settings";

/**
 * Workspaces (identidad v0.8): no hay "páginas" — el riel de navegación
 * cambia de instrumento sin abandonar el chasis (cabecera + barra de
 * estado siempre presentes). El Dashboard clásico y la vista Mapa suelta
 * han muerto: el Centro de Operaciones ES el mapa y ES el dashboard.
 */
export const VIEWS: { id: View; label: string; icon: string }[] = [
  { id: "ops", label: "Centro", icon: "◉" },
  { id: "nodes", label: "Flota", icon: "⬡" },
  { id: "jobs", label: "Trabajos", icon: "▶" },
  { id: "alerts", label: "Alertas", icon: "⚠" },
  { id: "profiles", label: "Perfiles", icon: "⧉" },
  { id: "config", label: "Config", icon: "⚙" },
  { id: "activity", label: "Registro", icon: "▤" },
  { id: "gateways", label: "Enlaces", icon: "⛭" },
  // Autenticación: "Usuarios" solo visible si eres admin O si el sistema aún
  // está en modo abierto (así siempre hay una forma de crear el primer
  // usuario); "Accesos" solo tiene sentido estando autenticado.
  { id: "users", label: "Usuarios", icon: "👤" },
  { id: "login-log", label: "Accesos", icon: "🔑" },
  // Panel "Ajustes": umbrales operacionales editables sin redeploy — mismo
  // criterio de visibilidad que Usuarios (RequireAdminDep en el backend).
  { id: "settings", label: "Ajustes", icon: "🎚" },
];

const VIEW_IDS = new Set<string>(VIEWS.map((v) => v.id));

/**
 * Ids históricos (componentes/documentos antiguos, y ahora también rutas
 * URL antiguas tipo `/dashboard`): siguen navegando bien.
 */
export function resolveView(v: string): View {
  if (v === "operations" || v === "batches") return "jobs";
  if (v === "dashboard" || v === "map") return "ops";
  if (VIEW_IDS.has(v)) return v as View;
  return "ops";
}

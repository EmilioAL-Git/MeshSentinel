/**
 * Riel de navegación vertical (identidad v0.8): sustituye al menú «Vistas ▾».
 * La navegación es parte del chasis — siempre visible, un glifo por
 * workspace, insignias vivas en Alertas y Trabajos. El Centro es el primero
 * y el destino del logo; no existe "página de inicio", existe el instrumento.
 */

export interface RailItem {
  id: string;
  icon: string;
  label: string;
  badge?: number;
  badgeCrit?: boolean;
}

/**
 * Llave inglesa monocroma (trazo, sin relleno) para Ajustes — sustituye al
 * emoji 🎚, a color e inconsistente con el resto de glifos del riel, que
 * heredan `currentColor` de `.navrail button`.
 */
function WrenchIcon() {
  return (
    <svg
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ verticalAlign: "-2px" }}
    >
      <path d="M14.7 6.3a4 4 0 0 0-5.4 4.9L3 17.5V21h3.5l6.3-6.3a4 4 0 0 0 4.9-5.4l-3 3-2.3-2.3z" />
    </svg>
  );
}

function RailIcon({ icon }: { icon: string }) {
  if (icon === "@wrench") return <WrenchIcon />;
  return <>{icon}</>;
}

export function NavRail({
  items,
  active,
  onNavigate,
}: {
  items: RailItem[];
  active: string;
  onNavigate: (id: string) => void;
}) {
  return (
    <nav className="navrail" aria-label="Workspaces">
      {items.map((it) => (
        <button
          key={it.id}
          className={active === it.id ? "on" : undefined}
          title={it.label}
          onClick={() => onNavigate(it.id)}
        >
          {it.badge != null && it.badge > 0 && (
            <span className={it.badgeCrit ? "badge crit" : "badge"}>
              {it.badge > 99 ? "99+" : it.badge}
            </span>
          )}
          <span aria-hidden>
            <RailIcon icon={it.icon} />
          </span>
          <span className="navlabel">{it.label}</span>
        </button>
      ))}
    </nav>
  );
}

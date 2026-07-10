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
          <span aria-hidden>{it.icon}</span>
          <span className="navlabel">{it.label}</span>
        </button>
      ))}
    </nav>
  );
}

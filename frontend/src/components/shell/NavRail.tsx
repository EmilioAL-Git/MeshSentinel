/**
 * Riel de navegación vertical (identidad v0.8): sustituye al menú «Vistas ▾».
 * La navegación es parte del chasis — siempre visible, un glifo por
 * workspace, insignias vivas en Alertas y Trabajos. El Centro es el primero
 * y el destino del logo; no existe "página de inicio", existe el instrumento.
 */

import { useState } from "react";
import { useIsMobile } from "../../hooks/useMediaQuery";

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

/** Cuántos destinos caben en la barra inferior móvil; el resto va a «Más». */
const MOBILE_PRIMARY = 4;

function NavButton({
  it,
  active,
  onNavigate,
}: {
  it: RailItem;
  active: boolean;
  onNavigate: (id: string) => void;
}) {
  return (
    <button className={active ? "on" : undefined} title={it.label} onClick={() => onNavigate(it.id)}>
      {it.badge != null && it.badge > 0 && (
        <span className={it.badgeCrit ? "badge crit" : "badge"}>{it.badge > 99 ? "99+" : it.badge}</span>
      )}
      <span aria-hidden>
        <RailIcon icon={it.icon} />
      </span>
      <span className="navlabel">{it.label}</span>
    </button>
  );
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
  const isMobile = useIsMobile();
  const [moreOpen, setMoreOpen] = useState(false);

  if (!isMobile) {
    return (
      <nav className="navrail" aria-label="Workspaces">
        {items.map((it) => (
          <NavButton key={it.id} it={it} active={active === it.id} onNavigate={onNavigate} />
        ))}
      </nav>
    );
  }

  // Móvil: barra inferior con los 4 destinos principales + «Más» (hoja con
  // el resto). Si el workspace activo vive en «Más», ese botón se resalta y
  // arrastra la insignia del resto para que una alerta nunca quede oculta.
  const primary = items.slice(0, MOBILE_PRIMARY);
  const rest = items.slice(MOBILE_PRIMARY);
  const restActive = rest.some((it) => it.id === active);
  const restBadge = rest.reduce((n, it) => n + (it.badge ?? 0), 0);
  const restCrit = rest.some((it) => it.badgeCrit);
  const go = (id: string) => {
    setMoreOpen(false);
    onNavigate(id);
  };
  return (
    <>
      {moreOpen && (
        <div className="navmore-backdrop" onClick={() => setMoreOpen(false)}>
          <div className="navmore" onClick={(e) => e.stopPropagation()}>
            {rest.map((it) => (
              <NavButton key={it.id} it={it} active={active === it.id} onNavigate={go} />
            ))}
          </div>
        </div>
      )}
      <nav className="navrail" aria-label="Workspaces">
        {primary.map((it) => (
          <NavButton key={it.id} it={it} active={active === it.id} onNavigate={go} />
        ))}
        {rest.length > 0 && (
          <button className={restActive || moreOpen ? "on" : undefined} onClick={() => setMoreOpen((o) => !o)}>
            {restBadge > 0 && <span className={restCrit ? "badge crit" : "badge"}>{restBadge > 99 ? "99+" : restBadge}</span>}
            <span aria-hidden>⋯</span>
            <span className="navlabel">Más</span>
          </button>
        )}
      </nav>
    </>
  );
}

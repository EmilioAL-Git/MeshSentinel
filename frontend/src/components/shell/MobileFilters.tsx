import { useState, type ReactNode } from "react";

/**
 * Filtros plegables SOLO en móvil. En escritorio es transparente (los hijos se
 * pintan en línea dentro de la toolbar, `display: contents`); en móvil queda un
 * botón «Filtros» y el resto de controles se despliega a pantalla completa de
 * ancho bajo la barra — antes 5-6 filas de selects comían media pantalla.
 * Estilos en mobile.css (`.mfilters`, `.m-only`).
 */
export function MobileFilters({ children, active = false }: { children: ReactNode; active?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        className={`btn m-only${active ? " primary" : ""}`}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        ⚙ Filtros{active ? " ●" : ""} {open ? "▴" : "▾"}
      </button>
      <div className={open ? "mfilters open" : "mfilters"}>{children}</div>
    </>
  );
}

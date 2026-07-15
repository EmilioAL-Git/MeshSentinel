import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { t } from "../../tokens";
import { FLEET_COLUMNS, type FleetColumnId } from "./instruments";

const MENU_WIDTH = 200;
const MENU_MAX_HEIGHT = 320;

/**
 * Selector de columnas opcionales del roster de Flota (pedido del usuario:
 * "quiero más columnas o que pueda elegirlas yo"). El desplegable se
 * renderiza en un portal a `document.body` con posición `fixed` calculada
 * desde el botón (`getBoundingClientRect`): así queda inmune a cualquier
 * `overflow` de un ancestro (p. ej. `.ws-scroll`, que al fijar solo
 * `overflow-y` convierte `overflow-x` en `auto` y recorta un `position:
 * absolute` normal — el bug reportado por el usuario, "se abre fuera de
 * vista y no se ve nada").
 */
export function ColumnPicker({
  visible,
  onChange,
}: {
  visible: FleetColumnId[];
  onChange: (v: FleetColumnId[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      const target = e.target as Node;
      if (btnRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, [open]);

  const openMenu = () => {
    const rect = btnRef.current?.getBoundingClientRect();
    if (!rect) return;
    const left = Math.min(Math.max(8, rect.right - MENU_WIDTH), window.innerWidth - MENU_WIDTH - 8);
    const fitsBelow = rect.bottom + MENU_MAX_HEIGHT + 8 <= window.innerHeight;
    const top = fitsBelow ? rect.bottom + 4 : Math.max(8, rect.top - MENU_MAX_HEIGHT - 4);
    setPos({ top, left });
    setOpen(true);
  };

  const toggle = (id: FleetColumnId) => {
    onChange(visible.includes(id) ? visible.filter((v) => v !== id) : [...visible, id]);
  };

  return (
    <>
      <button ref={btnRef} className="btn ghost" onClick={() => (open ? setOpen(false) : openMenu())} title="Elegir qué columnas mostrar">
        ⚙ Columnas
      </button>
      {open &&
        pos &&
        createPortal(
          <div
            ref={menuRef}
            style={{
              position: "fixed",
              top: pos.top,
              left: pos.left,
              zIndex: 990,
              width: MENU_WIDTH,
              maxHeight: MENU_MAX_HEIGHT,
              overflowY: "auto",
              background: t.surface,
              border: `1px solid ${t.border}`,
              borderRadius: 8,
              boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
              padding: "0.5rem",
              display: "flex",
              flexDirection: "column",
              gap: 2,
            }}
          >
            <div className="microlabel" style={{ marginBottom: 2 }}>
              Columnas del roster
            </div>
            {FLEET_COLUMNS.map((c) => (
              <label
                key={c.id}
                style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, padding: "0.2rem 0.3rem", cursor: "pointer" }}
              >
                <input type="checkbox" checked={visible.includes(c.id)} onChange={() => toggle(c.id)} />
                {c.label}
              </label>
            ))}
          </div>,
          document.body,
        )}
    </>
  );
}

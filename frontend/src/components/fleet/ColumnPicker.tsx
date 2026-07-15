import { useEffect, useRef, useState } from "react";
import { t } from "../../tokens";
import { FLEET_COLUMNS, type FleetColumnId } from "./instruments";

/**
 * Selector de columnas opcionales del roster de Flota (pedido del usuario:
 * "quiero más columnas o que pueda elegirlas yo"). Mismo patrón de menú
 * flotante que `AddToGroupMenu` — persistencia va en el `usePersistedState`
 * del padre (`FleetView`), aquí solo se alterna visibilidad.
 */
export function ColumnPicker({
  visible,
  onChange,
}: {
  visible: FleetColumnId[];
  onChange: (v: FleetColumnId[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, [open]);

  const toggle = (id: FleetColumnId) => {
    onChange(visible.includes(id) ? visible.filter((v) => v !== id) : [...visible, id]);
  };

  return (
    <div ref={rootRef} style={{ position: "relative" }}>
      <button className="btn ghost" onClick={() => setOpen((o) => !o)} title="Elegir qué columnas mostrar">
        ⚙ Columnas
      </button>
      {open && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            right: 0,
            zIndex: 500,
            minWidth: 190,
            maxHeight: 320,
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
        </div>
      )}
    </div>
  );
}

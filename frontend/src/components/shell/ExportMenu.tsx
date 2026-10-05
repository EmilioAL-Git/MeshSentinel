import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { t } from "../../tokens";

export interface ExportItem {
  label: string;
  /** Para qué sirve este formato, en una línea. */
  hint: string;
  onSelect: () => void;
}

const MENU_WIDTH = 250;

/**
 * Botón compacto «⤓ Exportar» con un menú de formatos. Mismo patrón de portal
 * `fixed` que ColumnPicker (inmune al `overflow` de los ancestros). Sustituye
 * al <select> de exportar, que ocupaba una fila entera y no explicaba nada.
 */
export function ExportMenu({ items, title }: { items: ExportItem[]; title: string }) {
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const open = pos != null;

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (btnRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setPos(null);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setPos(null);
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const toggle = () => {
    if (open) return setPos(null);
    const rect = btnRef.current?.getBoundingClientRect();
    if (!rect) return;
    const left = Math.min(Math.max(8, rect.right - MENU_WIDTH), window.innerWidth - MENU_WIDTH - 8);
    setPos({ top: rect.bottom + 4, left });
  };

  return (
    <>
      <button ref={btnRef} className="btn ghost" onClick={toggle} title={title}>
        ⤓ Exportar
      </button>
      {pos &&
        createPortal(
          <div
            ref={menuRef}
            style={{
              position: "fixed",
              top: pos.top,
              left: pos.left,
              zIndex: 990,
              width: MENU_WIDTH,
              background: t.surface,
              border: `1px solid ${t.border}`,
              borderRadius: 8,
              boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
              padding: "0.35rem",
              display: "flex",
              flexDirection: "column",
              gap: 2,
            }}
          >
            {items.map((item) => (
              <button
                key={item.label}
                className="btn ghost"
                style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", textAlign: "left", gap: 1, height: "auto", padding: "0.35rem 0.5rem" }}
                onClick={() => {
                  setPos(null);
                  item.onSelect();
                }}
              >
                <span style={{ fontWeight: 600, fontSize: 12.5 }}>{item.label}</span>
                <span style={{ color: t.textDim, fontSize: 11.5, fontWeight: 400, whiteSpace: "normal" }}>{item.hint}</span>
              </button>
            ))}
          </div>,
          document.body,
        )}
    </>
  );
}

import type { CSSProperties, ReactNode } from "react";
import { usePersistedState } from "../../hooks/usePersistedState";
import { t } from "../../tokens";

/**
 * Riel de iconos del panel derecho (v0.7 §6.1, decisión: riel, no pestañas):
 * los paneles permanecen montados (los buffers no se pierden) y solo se
 * alterna la visibilidad; clic en el icono activo pliega el panel dejando
 * solo el riel — convención VS Code. Escala a más paneles (Alertas, Consola
 * cruda) sin coste de layout.
 */

export interface RailPanelDef {
  id: string;
  icon: string;
  title: string;
  badge?: number;
  badgeColor?: string;
  content: ReactNode;
}

const railBtn = (active: boolean): CSSProperties => ({
  position: "relative",
  width: 40,
  height: 40,
  background: "transparent",
  border: "none",
  borderLeft: `2px solid ${active ? t.accent : "transparent"}`,
  color: active ? t.text : t.textDim,
  cursor: "pointer",
  fontSize: 15,
});

export function ConsoleRail({
  panels,
  width,
  open,
  onToggleOpen,
}: {
  panels: RailPanelDef[];
  width: number;
  /** Controlado por el padre (OpsCenter): permite además una flecha de borde simétrica a la del panel izquierdo. */
  open: boolean;
  onToggleOpen: (open: boolean) => void;
}) {
  const [activeId, setActiveId] = usePersistedState<string>("rail.active", panels[0]?.id ?? "");
  const active = panels.find((p) => p.id === activeId) ?? panels[0];

  return (
    <div style={{ display: "flex", height: "100%", borderLeft: `1px solid ${t.border}` }}>
      {/* Panel activo: todos montados, solo se alterna display (cambio instantáneo) */}
      {open && (
        <div style={{ width, background: t.surface, height: "100%", minWidth: 0 }}>
          {panels.map((p) => (
            <div key={p.id} style={{ display: p.id === active?.id ? "block" : "none", height: "100%" }}>
              {p.content}
            </div>
          ))}
        </div>
      )}
      {/* Riel de iconos, siempre visible */}
      <div
        style={{
          width: 40,
          background: t.surface,
          borderLeft: open ? `1px solid ${t.borderSubtle}` : "none",
          display: "flex",
          flexDirection: "column",
          paddingTop: 4,
        }}
      >
        {panels.map((p) => {
          const isActive = open && p.id === active?.id;
          return (
            <button
              key={p.id}
              title={p.title}
              style={railBtn(isActive)}
              onClick={() => {
                if (isActive) onToggleOpen(false); // clic en el activo = plegar
                else {
                  setActiveId(p.id);
                  onToggleOpen(true);
                }
              }}
            >
              {p.icon}
              {p.badge != null && p.badge > 0 && (
                <span
                  style={{
                    position: "absolute",
                    top: 3,
                    right: 3,
                    background: p.badgeColor ?? t.accent,
                    color: "#fff",
                    borderRadius: 8,
                    fontSize: 9,
                    lineHeight: "13px",
                    minWidth: 13,
                    padding: "0 2px",
                    fontFamily: t.fontMono,
                  }}
                >
                  {p.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

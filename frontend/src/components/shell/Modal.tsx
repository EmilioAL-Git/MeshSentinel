import type { CSSProperties, ReactNode } from "react";
import { t } from "../../tokens";

const overlayStyle: CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(0, 0, 0, 0.5)",
  zIndex: 1000,
  display: "flex",
  justifyContent: "center",
  alignItems: "flex-start",
  paddingTop: "10vh",
};

const boxStyle: CSSProperties = {
  width: "min(480px, 92vw)",
  maxHeight: "78vh",
  display: "flex",
  flexDirection: "column",
  background: t.surface,
  border: `1px solid ${t.border}`,
  borderRadius: 8,
  boxShadow: "0 12px 40px rgba(0, 0, 0, 0.55)",
  overflow: "hidden",
};

/** Modal genérico (mismo estilo que LoginModal) para los formularios de
 * creación/edición de reglas, integraciones y canales de AlertsView —
 * separa la lista (siempre visible) de la edición (siempre en ventana
 * aparte), pedido explícito del usuario. */
export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div style={overlayStyle} onMouseDown={onClose}>
      <div style={boxStyle} onMouseDown={(e) => e.stopPropagation()}>
        <div className="panel-head">
          <span className="panel-title">{title}</span>
          <button className="btn ghost" style={{ marginLeft: "auto", padding: "0.1rem 0.5rem", fontSize: 11 }} onClick={onClose}>
            ✕
          </button>
        </div>
        <div style={{ padding: "0.75rem", overflowY: "auto" }}>{children}</div>
      </div>
    </div>
  );
}

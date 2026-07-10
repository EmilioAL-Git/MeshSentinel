import type { CSSProperties } from "react";
import { t } from "./tokens";

// Estilos compartidos históricos, alineados con el lenguaje "consola" v0.8
// (console.css). Los componentes nuevos usan las clases CSS directamente;
// este objeto re-croma los workspaces heredados (Trabajos/Config/Perfiles)
// sin reescribirlos: card = panel del bastidor (anguloso, borde sutil).
export const styles: Record<string, CSSProperties> = {
  page: {
    fontFamily: t.fontUi,
    background: t.bg,
    color: t.text,
    minHeight: "100vh",
    padding: "1.5rem",
  },
  layout: { display: "grid", gridTemplateColumns: "2fr 1fr", gap: "0.75rem", alignItems: "start" },
  card: {
    background: t.surface,
    border: `1px solid ${t.borderSubtle}`,
    borderRadius: 3,
    padding: "0.85rem",
    marginBottom: "0.75rem",
  },
  table: { width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" },
  th: {
    textAlign: "left",
    padding: "0.35rem 0.6rem",
    borderBottom: `1px solid ${t.border}`,
    color: t.textFaint,
    fontSize: "0.68rem",
    fontWeight: 650,
    letterSpacing: "0.12em",
    textTransform: "uppercase",
  },
  td: { padding: "0.35rem 0.6rem", borderBottom: `1px solid ${t.borderSubtle}` },
  rowHover: { cursor: "pointer" },
  ok: { color: t.ok },
  bad: { color: t.crit },
  dim: { color: t.textDim },
  mono: { fontFamily: t.fontMono, fontSize: "0.85rem" },
  badgeOnline: {
    background: t.okTint,
    color: t.ok,
    border: `1px solid ${t.ok}`,
    borderRadius: 12,
    padding: "0.1rem 0.6rem",
    fontSize: "0.75rem",
  },
  badgeOffline: {
    background: "transparent",
    color: t.textDim,
    border: `1px solid ${t.border}`,
    borderRadius: 12,
    padding: "0.1rem 0.6rem",
    fontSize: "0.75rem",
  },
};

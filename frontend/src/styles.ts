import type { CSSProperties } from "react";
import { t } from "./tokens";

// Estilos compartidos históricos, ya sobre los tokens de la v0.7 (theme.css).
// Los componentes nuevos deberían usar los tokens (src/tokens.ts) directamente;
// este objeto se mantiene para no reescribir los componentes existentes.
export const styles: Record<string, CSSProperties> = {
  page: {
    fontFamily: t.fontUi,
    background: t.bg,
    color: t.text,
    minHeight: "100vh",
    padding: "1.5rem",
  },
  layout: { display: "grid", gridTemplateColumns: "2fr 1fr", gap: "1rem", alignItems: "start" },
  card: {
    background: t.surface,
    border: `1px solid ${t.border}`,
    borderRadius: 8,
    padding: "1rem",
    marginBottom: "1rem",
  },
  table: { width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" },
  th: { textAlign: "left", padding: "0.4rem 0.6rem", borderBottom: `1px solid ${t.border}`, color: t.textDim },
  td: { padding: "0.4rem 0.6rem", borderBottom: `1px solid ${t.borderSubtle}` },
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

import type { CSSProperties } from "react";

export const styles: Record<string, CSSProperties> = {
  page: {
    fontFamily: "system-ui, sans-serif",
    background: "#0d1117",
    color: "#e6edf3",
    minHeight: "100vh",
    padding: "1.5rem",
  },
  layout: { display: "grid", gridTemplateColumns: "2fr 1fr", gap: "1rem", alignItems: "start" },
  card: {
    background: "#161b22",
    border: "1px solid #30363d",
    borderRadius: 8,
    padding: "1rem",
    marginBottom: "1rem",
  },
  table: { width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" },
  th: { textAlign: "left", padding: "0.4rem 0.6rem", borderBottom: "1px solid #30363d", color: "#8b949e" },
  td: { padding: "0.4rem 0.6rem", borderBottom: "1px solid #21262d" },
  rowHover: { cursor: "pointer" },
  ok: { color: "#3fb950" },
  bad: { color: "#f85149" },
  dim: { color: "#8b949e" },
  mono: { fontFamily: "monospace", fontSize: "0.85rem" },
  badgeOnline: {
    background: "#1f6f43",
    color: "#fff",
    borderRadius: 12,
    padding: "0.1rem 0.6rem",
    fontSize: "0.75rem",
  },
  badgeOffline: {
    background: "#6e2c31",
    color: "#fff",
    borderRadius: 12,
    padding: "0.1rem 0.6rem",
    fontSize: "0.75rem",
  },
};

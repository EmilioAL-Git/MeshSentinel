import type { ReactNode } from "react";
import { usePersistedState } from "../../hooks/usePersistedState";
import { t } from "../../tokens";

/**
 * Bloque plegable del panel de estado (v0.7 §4): cabecera de una línea en
 * MAYÚSCULAS con badge, contenido denso debajo. El plegado persiste por
 * bloque. La ausencia de problema no ocupa espacio (principio 9): si
 * `emptyLabel` viene y `count` es 0, el contenido se sustituye por una
 * línea tenue.
 */
export function BlockAccordion({
  id,
  title,
  icon,
  count,
  countColor,
  emptyLabel,
  action,
  children,
}: {
  id: string;
  title: string;
  icon?: string;
  count?: number;
  countColor?: string;
  emptyLabel?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  const [open, setOpen] = usePersistedState<boolean>(`block.${id}.open`, true);
  const isEmpty = emptyLabel != null && (count ?? 0) === 0;
  return (
    <section style={{ borderBottom: `1px solid ${t.borderSubtle}` }}>
      <header
        onClick={() => setOpen(!open)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.45rem",
          padding: "0.55rem 0.9rem",
          cursor: "pointer",
          userSelect: "none",
        }}
      >
        <span
          style={{
            color: t.textDim,
            fontSize: 11,
            letterSpacing: "0.08em",
            fontWeight: 600,
          }}
        >
          {icon && <span style={{ marginRight: 5 }}>{icon}</span>}
          {title.toUpperCase()}
        </span>
        {count != null && count > 0 && (
          <span
            style={{
              color: countColor ?? t.textDim,
              fontFamily: t.fontMono,
              fontSize: 11,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            ({count})
          </span>
        )}
        <span style={{ marginLeft: "auto", display: "inline-flex", gap: "0.5rem", alignItems: "center" }}>
          {action}
          <span style={{ color: t.textFaint, fontSize: 10 }}>{open ? "▾" : "▸"}</span>
        </span>
      </header>
      {open &&
        (isEmpty ? (
          <p style={{ color: t.textFaint, fontSize: 12, margin: 0, padding: "0 0.9rem 0.6rem" }}>
            {emptyLabel}
          </p>
        ) : (
          <div style={{ padding: "0 0.9rem 0.7rem" }}>{children}</div>
        ))}
    </section>
  );
}

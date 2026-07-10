import { useMemo, useState, type CSSProperties } from "react";
import type { ActivityCategory, ActivityEntry } from "../../activity";
import { t } from "../../tokens";

/**
 * Consola de actividad del Centro de Operaciones (v0.7 §6.3): qué está
 * ocurriendo AHORA, pensada para quedar abierta horas — mono compacta,
 * 1-2 líneas por entrada, borde izquierdo de color por severidad (el color
 * marca, no grita). La investigación con filtros completos y exportación es
 * la vista Actividad, no esta consola.
 */

const SEVERITY_COLOR: Record<ActivityEntry["severity"], string> = {
  info: t.border,
  ok: t.ok,
  warn: t.warn,
  error: t.crit,
};

type Level = "todo" | "admin" | "alertas";

const LEVEL_CATEGORIES: Record<Level, Set<ActivityCategory> | null> = {
  todo: null,
  admin: new Set<ActivityCategory>(["operacion", "batch"]),
  alertas: new Set<ActivityCategory>(["alerta"]),
};

const levelBtn = (active: boolean): CSSProperties => ({
  background: active ? t.accentTint : "transparent",
  border: `1px solid ${active ? t.accent : t.border}`,
  color: active ? t.accent : t.textDim,
  borderRadius: 10,
  cursor: "pointer",
  fontSize: 11,
  padding: "0 0.5rem",
});

export function ActivityPanel({
  entries,
  onOpenNode,
}: {
  entries: ActivityEntry[];
  onOpenNode: (nodeId: string) => void;
}) {
  const [level, setLevel] = useState<Level>("todo");
  const filtered = useMemo(() => {
    const cats = LEVEL_CATEGORIES[level];
    return cats == null ? entries : entries.filter((e) => cats.has(e.category));
  }, [entries, level]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.4rem",
          padding: "0.5rem 0.75rem",
          borderBottom: `1px solid ${t.borderSubtle}`,
        }}
      >
        <span style={{ color: t.textDim, fontSize: 11, letterSpacing: "0.08em", fontWeight: 600 }}>
          ACTIVIDAD
        </span>
        <span style={{ color: t.ok, fontSize: 10 }}>● en vivo</span>
        <span style={{ marginLeft: "auto", display: "flex", gap: "0.3rem" }}>
          {(["todo", "admin", "alertas"] as Level[]).map((l) => (
            <button key={l} style={levelBtn(level === l)} onClick={() => setLevel(l)}>
              {l}
            </button>
          ))}
        </span>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "0.25rem 0" }}>
        {filtered.length === 0 && (
          <p style={{ color: t.textFaint, fontSize: 12, padding: "0.5rem 0.75rem", margin: 0 }}>
            Esperando eventos…
          </p>
        )}
        {filtered.map((e) => (
          <div
            key={e.id}
            style={{
              borderLeft: `2px solid ${SEVERITY_COLOR[e.severity]}`,
              padding: "0.22rem 0.6rem 0.22rem 0.55rem",
              margin: "0 0 1px 0.35rem",
              fontSize: 12,
              lineHeight: 1.35,
            }}
          >
            <span style={{ fontFamily: t.fontMono, color: t.textFaint, fontSize: 11, marginRight: 6 }}>
              {e.time}
            </span>
            {e.nodeId ? (
              <span
                onClick={() => onOpenNode(e.nodeId!)}
                style={{ color: t.textDim, cursor: "pointer" }}
                title="Abrir el nodo"
              >
                {e.text}
              </span>
            ) : (
              <span style={{ color: t.textDim }}>{e.text}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

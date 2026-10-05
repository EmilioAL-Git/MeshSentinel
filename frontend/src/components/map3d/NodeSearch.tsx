import { useMemo, useState } from "react";
import type { NodeSummaryOut } from "../../api/client";
import { t } from "../../tokens";

const MAX_RESULTS = 30;

export const nodeLabel = (s: NodeSummaryOut) => s.node.long_name || s.node.short_name || s.node.node_id;

/** Buscador de nodos por nombre, nombre corto o id (sin ignorados). */
export function NodeSearch({
  summaries,
  onPick,
  placeholder = "Buscar nodo por nombre o id…",
  exclude,
  autoFocus,
}: {
  summaries: NodeSummaryOut[];
  onPick: (id: string) => void;
  placeholder?: string;
  exclude?: string[];
  autoFocus?: boolean;
}) {
  const [q, setQ] = useState("");
  const results = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const pool = summaries.filter((s) => !s.node.is_ignored && !exclude?.includes(s.node.node_id));
    const hits = needle
      ? pool.filter((s) =>
          [s.node.long_name, s.node.short_name, s.node.node_id].some((v) => v?.toLowerCase().includes(needle)),
        )
      : pool;
    // Sin texto: los vistos más recientemente; con texto: los que empiezan por él primero
    return hits
      .sort((a, b) => {
        if (needle) {
          const sa = nodeLabel(a).toLowerCase().startsWith(needle) ? 0 : 1;
          const sb = nodeLabel(b).toLowerCase().startsWith(needle) ? 0 : 1;
          if (sa !== sb) return sa - sb;
        }
        return (b.node.last_seen_at ?? "").localeCompare(a.node.last_seen_at ?? "");
      })
      .slice(0, MAX_RESULTS);
  }, [summaries, q, exclude]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <input
        className="input"
        value={q}
        autoFocus={autoFocus}
        placeholder={placeholder}
        onChange={(e) => setQ(e.target.value)}
        aria-label="Buscar nodo"
      />
      <div style={{ display: "flex", flexDirection: "column", maxHeight: 220, overflowY: "auto" }}>
        {results.map((s) => (
          <button
            key={s.node.node_id}
            className="btn"
            style={{ display: "flex", gap: 6, alignItems: "center", textAlign: "left", border: 0, padding: "4px 6px" }}
            onClick={() => {
              onPick(s.node.node_id);
              setQ("");
            }}
          >
            <span style={{ color: s.node.online ? t.ok : t.textFaint }} aria-hidden>
              ●
            </span>
            <span style={{ flex: 1, overflowWrap: "anywhere" }}>{nodeLabel(s)}</span>
            <span className="mono" style={{ fontSize: 10.5, color: t.textDim }}>
              {s.last_position ? s.node.short_name ?? "" : "sin GPS"}
            </span>
          </button>
        ))}
        {results.length === 0 && <div className="empty">Ningún nodo coincide.</div>}
      </div>
    </div>
  );
}

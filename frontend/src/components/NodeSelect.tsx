import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { displayName, type NodeSummaryOut } from "../api/client";
import { styles } from "../styles";

const wrap: CSSProperties = { position: "relative", display: "inline-block" };

const input: CSSProperties = {
  background: "#0d1117",
  border: "1px solid #30363d",
  color: "#e6edf3",
  borderRadius: 6,
  padding: "0.3rem 0.5rem",
  width: "100%",
  boxSizing: "border-box",
};

const dropdown: CSSProperties = {
  position: "absolute",
  top: "calc(100% + 2px)",
  left: 0,
  zIndex: 20,
  background: "#161b22",
  border: "1px solid #30363d",
  borderRadius: 6,
  maxHeight: 220,
  overflowY: "auto",
  width: "max-content",
  minWidth: "100%",
  boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
};

const optionStyle: CSSProperties = {
  padding: "0.35rem 0.6rem",
  cursor: "pointer",
  whiteSpace: "nowrap",
  fontSize: "0.88rem",
};

function matches(s: NodeSummaryOut, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q === "") return true;
  return (
    s.node.node_id.toLowerCase().includes(q) ||
    (s.node.long_name ?? "").toLowerCase().includes(q) ||
    (s.node.short_name ?? "").toLowerCase().includes(q)
  );
}

/** Selector de nodo con buscador (filtra por nombre/short_name/node_id
 * mientras se escribe). Sustituye a los `<select>` planos: con decenas de
 * nodos en la malla, encontrar uno por nombre en una lista sin filtrar es
 * poco práctico. */
export function NodeSelect({
  value,
  onChange,
  options,
  placeholder = "— nodo —",
  showOnlineStatus = false,
  style,
}: {
  value: string;
  onChange: (nodeId: string) => void;
  options: NodeSummaryOut[];
  placeholder?: string;
  showOnlineStatus?: boolean;
  style?: CSSProperties;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);

  const selected = options.find((s) => s.node.node_id === value);
  const filtered = useMemo(() => options.filter((s) => matches(s, query)), [options, query]);

  useEffect(() => {
    if (!open) return;
    const onClickOutside = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  const pick = (nodeId: string) => {
    onChange(nodeId);
    setQuery("");
    setOpen(false);
  };

  const label = (s: NodeSummaryOut) =>
    showOnlineStatus ? `${displayName(s.node)} ${s.node.online ? "· online" : "· offline"}` : displayName(s.node);

  return (
    <div ref={rootRef} style={{ ...wrap, ...style }}>
      <input
        style={input}
        placeholder={selected ? label(selected) : placeholder}
        value={open ? query : ""}
        onFocus={() => {
          setOpen(true);
          setHighlight(0);
        }}
        onChange={(e) => {
          setQuery(e.target.value);
          setHighlight(0);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setHighlight((h) => Math.min(h + 1, filtered.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setHighlight((h) => Math.max(h - 1, 0));
          } else if (e.key === "Enter") {
            e.preventDefault();
            const pickedOption = filtered[highlight];
            if (pickedOption) pick(pickedOption.node.node_id);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
      />
      {open && (
        <div style={dropdown}>
          {value !== "" && (
            <div
              style={{ ...optionStyle, ...styles.dim }}
              onMouseDown={(e) => {
                e.preventDefault();
                pick("");
              }}
            >
              {placeholder}
            </div>
          )}
          {filtered.length === 0 && <div style={{ ...optionStyle, ...styles.dim }}>Sin resultados</div>}
          {filtered.map((s, i) => (
            <div
              key={s.node.node_id}
              style={{
                ...optionStyle,
                background: i === highlight ? "#1f6feb33" : undefined,
                fontWeight: s.node.node_id === value ? 600 : 400,
              }}
              onMouseEnter={() => setHighlight(i)}
              onMouseDown={(e) => {
                e.preventDefault();
                pick(s.node.node_id);
              }}
            >
              {label(s)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

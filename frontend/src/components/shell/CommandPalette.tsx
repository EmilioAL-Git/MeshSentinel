import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { GatewayOut, GroupOut, NodeSummaryOut, ProfileOut, TagOut } from "../../api/client";
import { fuzzyScore } from "../../search";
import { t } from "../../tokens";

/**
 * Búsqueda global ⌘K / Ctrl+K (v0.7 §10): paleta modal con fuzzy matching
 * client-side sobre las queries ya cacheadas — cero endpoints nuevos.
 * v0.7.0 = estructura completa con nodos, gateways, etiquetas, grupos,
 * perfiles y acciones de navegación; los ámbitos de operaciones/lotes/
 * secciones de config y las acciones contextuales llegan con sus fases.
 * Prefijos: ">" acciones · "!" nodos por id · "@" gateways.
 */

export interface PaletteItem {
  kind: "node" | "gateway" | "tag" | "group" | "profile" | "action";
  key: string;
  label: string;
  /** Texto adicional donde también se busca (p. ej. el node_id). */
  altText?: string;
  meta?: string;
  statusColor?: string;
  run: () => void;
}

const KIND_LABEL: Record<PaletteItem["kind"], string> = {
  node: "NODOS",
  gateway: "GATEWAYS",
  tag: "ETIQUETAS",
  group: "GRUPOS",
  profile: "PERFILES",
  action: "ACCIONES",
};

const KIND_ORDER: PaletteItem["kind"][] = ["node", "gateway", "tag", "group", "profile", "action"];

const overlayStyle: CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(0, 0, 0, 0.5)",
  zIndex: 1000,
  display: "flex",
  justifyContent: "center",
  alignItems: "flex-start",
  paddingTop: "12vh",
};

const boxStyle: CSSProperties = {
  width: "min(600px, 92vw)",
  background: t.surface,
  border: `1px solid ${t.border}`,
  borderRadius: 8,
  boxShadow: "0 12px 40px rgba(0, 0, 0, 0.55)",
  overflow: "hidden",
};

export function CommandPalette({
  open,
  onClose,
  summaries,
  gateways,
  tags,
  groups,
  profiles,
  onNavigate,
  onOpenNode,
  onFilterTag,
  onFilterGroup,
  views,
}: {
  open: boolean;
  onClose: () => void;
  summaries: NodeSummaryOut[];
  gateways: GatewayOut[];
  tags: TagOut[];
  groups: GroupOut[];
  profiles: ProfileOut[];
  onNavigate: (view: string) => void;
  onOpenNode: (nodeId: string) => void;
  onFilterTag: (tagName: string) => void;
  onFilterGroup: (groupId: number) => void;
  views: { id: string; label: string }[];
}) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
      // El input existe en el mismo render: enfocar tras el paint
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const allItems = useMemo<PaletteItem[]>(() => {
    if (!open) return [];
    const items: PaletteItem[] = [];
    for (const s of summaries) {
      const name = s.node.long_name || s.node.short_name || s.node.node_id;
      const battery = s.last_device_telemetry?.battery_level;
      items.push({
        kind: "node",
        key: `node:${s.node.node_id}`,
        label: `${name} (${s.node.node_id})`,
        altText: s.node.node_id,
        meta: [
          s.node.online ? "online" : "offline",
          battery != null ? (battery > 100 ? "⚡ ext." : `${battery}%`) : null,
          s.node.gateway_id,
        ]
          .filter(Boolean)
          .join(" · "),
        statusColor: s.node.online ? t.ok : t.textFaint,
        run: () => onOpenNode(s.node.node_id),
      });
    }
    for (const g of gateways) {
      if (g.deleted_at != null) continue;
      items.push({
        kind: "gateway",
        key: `gw:${g.gateway_id}`,
        label: g.name ? `${g.gateway_id} — ${g.name}` : g.gateway_id,
        meta: [g.transport, g.status].filter(Boolean).join(", "),
        statusColor: g.status === "connected" ? t.ok : t.crit,
        run: () => onNavigate("gateways"),
      });
    }
    for (const tag of tags) {
      items.push({
        kind: "tag",
        key: `tag:${tag.id}`,
        label: tag.name,
        meta: "etiqueta",
        run: () => onFilterTag(tag.name),
      });
    }
    for (const g of groups) {
      items.push({
        kind: "group",
        key: `group:${g.id}`,
        label: g.name,
        meta: `grupo · ${g.member_count} nodos`,
        run: () => onFilterGroup(g.id),
      });
    }
    for (const p of profiles) {
      items.push({
        kind: "profile",
        key: `profile:${p.id}`,
        label: `${p.name} v${p.latest_version}`,
        meta: "perfil",
        run: () => onNavigate("profiles"),
      });
    }
    for (const v of views) {
      items.push({
        kind: "action",
        key: `goto:${v.id}`,
        label: `Ir a: ${v.label}`,
        run: () => onNavigate(v.id),
      });
    }
    return items;
  }, [open, summaries, gateways, tags, groups, profiles, views, onNavigate, onOpenNode, onFilterTag, onFilterGroup]);

  const results = useMemo(() => {
    let q = query.trim();
    let kinds: PaletteItem["kind"][] | null = null;
    if (q.startsWith(">")) {
      kinds = ["action"];
      q = q.slice(1).trim();
    } else if (q.startsWith("!")) {
      kinds = ["node"];
      // el "!" forma parte del node_id canónico: se busca con él incluido
    } else if (q.startsWith("@")) {
      kinds = ["gateway"];
      q = q.slice(1).trim();
    }
    const pool = kinds ? allItems.filter((i) => kinds.includes(i.kind)) : allItems;
    if (q === "") {
      // Sin consulta: acciones primero (navegación rápida), luego el resto
      return [...pool].sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind)).slice(0, 12);
    }
    const scored: { item: PaletteItem; score: number }[] = [];
    for (const item of pool) {
      const scores = [fuzzyScore(q, item.label), item.altText != null ? fuzzyScore(q, item.altText) : null];
      const best = Math.max(...scores.map((sc) => (sc == null ? -Infinity : sc)));
      if (best !== -Infinity) scored.push({ item, score: best });
    }
    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, 12).map((sc) => sc.item);
  }, [query, allItems]);

  useEffect(() => setCursor(0), [results.length, query]);

  if (!open) return null;

  const grouped: { kind: PaletteItem["kind"]; items: { item: PaletteItem; index: number }[] }[] = [];
  results.forEach((item, index) => {
    const last = grouped[grouped.length - 1];
    if (last && last.kind === item.kind) last.items.push({ item, index });
    else grouped.push({ kind: item.kind, items: [{ item, index }] });
  });

  const run = (item: PaletteItem) => {
    onClose();
    item.run();
  };

  return (
    <div style={overlayStyle} onMouseDown={onClose}>
      <div style={boxStyle} onMouseDown={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Buscar nodos, gateways, perfiles, grupos…  (> acciones · ! id · @ gateway)"
          style={{
            width: "100%",
            background: "transparent",
            border: "none",
            borderBottom: `1px solid ${t.border}`,
            outline: "none",
            color: t.text,
            fontFamily: t.fontUi,
            fontSize: 15,
            padding: "0.8rem 1rem",
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              // Corta la propagación: Esc aquí solo cierra la paleta, no
              // el cajón de detalle que escucha en window (OpsCenter)
              e.stopPropagation();
              onClose();
            }
            else if (e.key === "ArrowDown") {
              e.preventDefault();
              setCursor((c) => Math.min(c + 1, results.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setCursor((c) => Math.max(c - 1, 0));
            } else if (e.key === "Enter" && results[cursor]) {
              run(results[cursor]);
            }
          }}
        />
        <div ref={listRef} style={{ maxHeight: "50vh", overflowY: "auto", padding: "0.4rem 0" }}>
          {results.length === 0 && (
            <p style={{ color: t.textDim, padding: "0.6rem 1rem", margin: 0 }}>Sin resultados.</p>
          )}
          {grouped.map((group) => (
            <div key={group.kind}>
              <div
                style={{
                  color: t.textFaint,
                  fontSize: 10.5,
                  letterSpacing: "0.08em",
                  padding: "0.35rem 1rem 0.15rem",
                }}
              >
                {KIND_LABEL[group.kind]}
              </div>
              {group.items.map(({ item, index }) => (
                <div
                  key={item.key}
                  onMouseEnter={() => setCursor(index)}
                  onClick={() => run(item)}
                  style={{
                    display: "flex",
                    alignItems: "baseline",
                    gap: "0.6rem",
                    padding: "0.3rem 1rem",
                    cursor: "pointer",
                    background: index === cursor ? t.accentTint : "transparent",
                    borderLeft: `2px solid ${index === cursor ? t.accent : "transparent"}`,
                  }}
                >
                  {item.statusColor && <span style={{ color: item.statusColor, fontSize: 10 }}>●</span>}
                  <span style={{ color: t.text }}>{item.label}</span>
                  {item.meta && <span style={{ color: t.textDim, fontSize: 12 }}>{item.meta}</span>}
                </div>
              ))}
            </div>
          ))}
        </div>
        <div
          style={{
            borderTop: `1px solid ${t.borderSubtle}`,
            color: t.textFaint,
            fontSize: 11,
            padding: "0.35rem 1rem",
            fontFamily: t.fontMono,
          }}
        >
          ↑↓ navegar · ⏎ abrir · Esc cerrar
        </div>
      </div>
    </div>
  );
}

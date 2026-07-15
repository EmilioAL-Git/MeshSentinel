import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  CATEGORY_LABEL,
  originDestination,
  packetColor,
  PACKET_FILTERS,
  toEntry,
  type ActivityCategory,
  type ActivityEntry,
  type ActivityPriority,
  type ActivitySeverity,
} from "../activity";
import { fetchActivityLog, type GatewayOut, type NodeSummaryOut } from "../api/client";
import { useActiveGroup, useGroupNodeIds } from "../context/GroupContext";
import { usePersistedState } from "../hooks/usePersistedState";
import { useUrlList, useUrlString } from "../hooks/useUrlState";
import { NodeSelect } from "./NodeSelect";

/**
 * Registro (consola profesional): el diario/consola de paquetes de la red,
 * respaldado por el histórico persistente COMPLETO del backend.
 *
 * - Stream en vivo (WS) fusionado con páginas del histórico (`GET /activity`,
 *   scroll infinito hacia abajo por `before_id`).
 * - Filtros de SERVIDOR: nodo, pasarela, grupo activo y búsqueda de texto
 *   libre — funcionan sobre TODO el histórico, no sobre el buffer.
 * - Pausa del stream (manual, o automática al hacer scroll: leer nunca
 *   compite con el tráfico entrante) con contador de eventos retenidos.
 * - Agrupación OPCIONAL de ráfagas repetitivas (mismo nodo + mismo tipo,
 *   ≥3 seguidas) — solo presentación: un paquete = una entrada, siempre;
 *   la ráfaga se expande a sus entradas individuales.
 */

const RECENT_WINDOW_MS = 60_000;
const PAGE_SIZE = 100;
const BURST_MIN = 3;

const SEVERITY_COLOR: Record<ActivitySeverity, string> = {
  info: "var(--text-dim)",
  ok: "var(--ok)",
  warn: "var(--warn)",
  error: "var(--crit)",
};

const PRIORITY_COLOR: Record<ActivityPriority, string> = {
  info: "var(--text-dim)",
  important: "var(--accent)",
  warning: "var(--warn)",
  critical: "var(--crit)",
};

const CATEGORY_COLOR: Record<ActivityCategory, string> = {
  operacion: "var(--accent)",
  batch: "var(--accent)",
  pasarela: "var(--ok)",
  alerta: "var(--crit)",
  malla: "var(--text-faint)",
};

const ALL_CATEGORIES = Object.keys(CATEGORY_LABEL) as ActivityCategory[];

/** Una fila visible: entrada suelta, o ráfaga plegada de entradas iguales. */
type VisibleRow =
  | { kind: "entry"; entry: ActivityEntry }
  | { kind: "burst"; key: string; entries: ActivityEntry[] };

export function ActivityConsole({
  entries,
  summaries,
  gateways,
}: {
  /** Stream en vivo (WS) que mantiene App — la cabeza de la consola. */
  entries: ActivityEntry[];
  summaries: NodeSummaryOut[];
  gateways: GatewayOut[];
}) {
  const { activeGroup, activeGroupId } = useActiveGroup();
  const groupNodeIds = useGroupNodeIds(summaries);

  // ── Filtros ↔ URL (`activity.*`, ADR 0026 / docs/design/urls-compartibles.md
  // §3.5) ──────────────────────────────────────────────────────────────────
  // Servidor (recortan TODO el histórico): nodo, pasarela, grupo, búsqueda.
  // Cliente (visuales, sobre lo cargado): categorías, tipo de paquete, lote.
  // `groupBursts` es presentación, no filtro — se queda en localStorage.
  const [nodeFilterRaw, setNodeFilter] = useUrlString("activity.node", "", { replace: true });
  const [gatewayFilterRaw, setGatewayFilter] = useUrlString("activity.gw", "", { replace: true });
  const [urlQ, setUrlQ] = useUrlString("activity.q", "", { replace: true });
  const [batchFilterRaw, setBatchFilter] = useUrlString("activity.batch", "", { replace: true });
  const [categoriesList, setCategoriesList] = useUrlList("activity.cat", ALL_CATEGORIES, { replace: true });
  const [packetFilterRaw, setPacketFilter] = useUrlString("activity.packet", "", { replace: true });
  const [groupBursts, setGroupBursts] = usePersistedState<boolean>("activity.groupBursts", true);
  const nodeFilter = nodeFilterRaw ?? "";
  const gatewayFilter = gatewayFilterRaw ?? "";
  const batchFilter = batchFilterRaw ?? "";
  const packetFilter = packetFilterRaw ?? "";
  const categories = useMemo(() => new Set(categoriesList) as Set<ActivityCategory>, [categoriesList]);

  // El campo de texto sigue siendo estado local (tecleo sin debounce); solo
  // el valor YA pedido al servidor (`debouncedSearch`) se refleja en la URL
  // — así un enlace compartido reproduce lo que de verdad se buscó, no un
  // carácter a medio escribir. El valor inicial sí puede venir de la URL.
  const [search, setSearch] = useState(urlQ ?? "");
  const [debouncedSearch, setDebouncedSearch] = useState(urlQ ?? "");

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const trimmed = search.trim();
      setDebouncedSearch(trimmed);
      setUrlQ(trimmed);
    }, 350);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const serverFilters = useMemo(
    () => ({
      nodeId: nodeFilter || undefined,
      gatewayId: gatewayFilter || undefined,
      groupId: activeGroupId ?? undefined,
      q: debouncedSearch || undefined,
    }),
    [nodeFilter, gatewayFilter, activeGroupId, debouncedSearch],
  );

  // ── Histórico persistente: scroll infinito por before_id ─────────────────
  const history = useInfiniteQuery({
    queryKey: ["activity-log", serverFilters],
    queryFn: ({ pageParam }) => fetchActivityLog(PAGE_SIZE, { ...serverFilters, beforeId: pageParam }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => (last.length === PAGE_SIZE ? last[last.length - 1].log_id : undefined),
  });
  const serverEntries = useMemo(() => {
    const out: ActivityEntry[] = [];
    for (const page of history.data?.pages ?? []) {
      for (const item of page) {
        const e = toEntry(item);
        if (e) out.push(e);
      }
    }
    return out;
  }, [history.data]);

  // ── Stream en vivo: réplica client-side de los filtros de servidor ───────
  const matchesFilters = useMemo(() => {
    const needle = debouncedSearch.toLowerCase();
    return (e: ActivityEntry): boolean => {
      if (nodeFilter && e.nodeId !== nodeFilter) return false;
      if (gatewayFilter && e.gatewayId !== gatewayFilter) return false;
      // Grupo: misma regla que el servidor — sin nodo, siempre visible
      if (groupNodeIds != null && e.nodeId != null && !groupNodeIds.has(e.nodeId)) return false;
      if (needle) {
        const haystack = [
          e.text,
          e.description ?? "",
          e.nodeLabel ?? "",
          e.nodeId ?? "",
          e.packetType ?? "",
          ...(e.details ?? []).flat(),
        ]
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      return true;
    };
  }, [nodeFilter, gatewayFilter, groupNodeIds, debouncedSearch]);

  // ── Pausa del stream + scroll inteligente ─────────────────────────────────
  // El stream se congela al pausar manualmente O al alejarse del principio
  // (leer nunca compite con el tráfico entrante). Los eventos retenidos se
  // cuentan y entran de golpe al reanudar/volver arriba.
  const [manualPaused, setManualPaused] = useState(false);
  const [scrolledAway, setScrolledAway] = useState(false);
  const frozen = manualPaused || scrolledAway;
  const [freezeTs, setFreezeTs] = useState<number | null>(null);
  useEffect(() => {
    setFreezeTs((current) => (frozen ? (current ?? Date.now()) : null));
  }, [frozen]);

  const liveShown = useMemo(
    () => entries.filter((e) => matchesFilters(e) && (freezeTs == null || e.receivedAtMs <= freezeTs)),
    [entries, matchesFilters, freezeTs],
  );
  const pendingCount = useMemo(
    () => (freezeTs == null ? 0 : entries.filter((e) => matchesFilters(e) && e.receivedAtMs > freezeTs).length),
    [entries, matchesFilters, freezeTs],
  );

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    // Arriba del todo = seguir el directo; alejado = congelar la cabeza
    if (el.scrollTop > 80 && !scrolledAway) setScrolledAway(true);
    else if (el.scrollTop <= 10 && scrolledAway) setScrolledAway(false);
    // Cerca del fondo = cargar una página más de histórico
    if (
      el.scrollHeight - el.scrollTop - el.clientHeight < 400 &&
      history.hasNextPage &&
      !history.isFetchingNextPage
    ) {
      void history.fetchNextPage();
    }
  };
  const backToLive = () => {
    setManualPaused(false);
    setScrolledAway(false);
    scrollRef.current?.scrollTo({ top: 0 });
  };

  // ── Fusión en vivo + histórico (dedupe por event_id) y filtros de cliente ─
  const merged = useMemo(() => {
    const seen = new Set<string>();
    const out: ActivityEntry[] = [];
    for (const e of [...liveShown, ...serverEntries]) {
      if (seen.has(e.id)) continue;
      seen.add(e.id);
      out.push(e);
    }
    out.sort((a, b) => b.receivedAtMs - a.receivedAtMs);
    return out;
  }, [liveShown, serverEntries]);

  const filtered = useMemo(
    () =>
      merged.filter(
        (e) =>
          categories.has(e.category) &&
          (batchFilter === "" || e.batchId === Number(batchFilter)) &&
          (packetFilter === "" ||
            PACKET_FILTERS.find((f) => f.key === packetFilter)?.types.includes(e.packetType ?? "")),
      ),
    [merged, categories, batchFilter, packetFilter],
  );

  // ── Ráfagas: plegado OPCIONAL de repeticiones consecutivas ───────────────
  // Solo presentación: mismo nodo + mismo tipo de paquete, ≥3 seguidas.
  const rows = useMemo<VisibleRow[]>(() => {
    if (!groupBursts) return filtered.map((entry) => ({ kind: "entry", entry }));
    const out: VisibleRow[] = [];
    let i = 0;
    while (i < filtered.length) {
      const e = filtered[i];
      const key = e.packetType != null && e.nodeId != null ? `${e.nodeId}|${e.packetType}` : null;
      if (key == null) {
        out.push({ kind: "entry", entry: e });
        i += 1;
        continue;
      }
      let j = i + 1;
      while (
        j < filtered.length &&
        filtered[j].nodeId === e.nodeId &&
        filtered[j].packetType === e.packetType
      ) {
        j += 1;
      }
      if (j - i >= BURST_MIN) {
        out.push({ kind: "burst", key: `${key}|${e.id}`, entries: filtered.slice(i, j) });
      } else {
        for (let k = i; k < j; k += 1) out.push({ kind: "entry", entry: filtered[k] });
      }
      i = j;
    }
    return out;
  }, [filtered, groupBursts]);

  const [expandedBursts, setExpandedBursts] = useState<Set<string>>(new Set());
  const toggleBurst = (key: string) => {
    setExpandedBursts((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // "Ver paquete" (capa técnica por entrada), como siempre
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggleExpanded = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Resumen de tráfico del último minuto (sobre lo visible)
  const [ticker, setTicker] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setTicker((n) => n + 1), 2000);
    return () => window.clearInterval(id);
  }, []);
  const recentCounts = useMemo(() => {
    void ticker;
    const cutoff = Date.now() - RECENT_WINDOW_MS;
    const counts = new Map<string, number>(PACKET_FILTERS.map((f) => [f.key, 0]));
    for (const e of merged) {
      if (!e.packetType || e.receivedAtMs < cutoff) continue;
      const bucket = PACKET_FILTERS.find((f) => f.types.includes(e.packetType!));
      if (bucket) counts.set(bucket.key, (counts.get(bucket.key) ?? 0) + 1);
    }
    return counts;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [merged, ticker]);

  const batchIds = useMemo(
    () =>
      [...new Set(merged.map((e) => e.batchId).filter((b): b is number => b != null))].sort((a, b) => b - a),
    [merged],
  );
  const gatewayIds = useMemo(() => {
    const ids = new Set(gateways.map((g) => g.gateway_id));
    for (const e of merged) if (e.gatewayId && e.gatewayId !== "system") ids.add(e.gatewayId);
    return [...ids].sort();
  }, [merged, gateways]);

  const toggleCategory = (c: ActivityCategory) => {
    const next = new Set(categories);
    if (next.has(c)) next.delete(c);
    else next.add(c);
    setCategoriesList([...next]);
  };

  return (
    <div className="ws">
      <div className="toolbar">
        <span className="microlabel">Registro</span>
        {frozen ? (
          <button
            className="btn ghost"
            style={{ color: "var(--warn)", borderColor: "var(--warn)" }}
            onClick={backToLive}
            title="El stream está en pausa; los eventos nuevos se retienen"
          >
            ⏸ pausado{pendingCount > 0 ? ` · ${pendingCount} nuevos` : ""} — reanudar
          </button>
        ) : (
          <>
            <span className="noc-pulse" style={{ color: "var(--ok)", fontSize: 9 }}>●</span>
            <span className="mono" style={{ fontSize: 11, color: "var(--ok)" }}>en vivo</span>
            <button className="btn ghost" onClick={() => setManualPaused(true)} title="Congelar el stream para leer con calma">
              ⏸
            </button>
          </>
        )}
        <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>
          {filtered.length} eventos{history.hasNextPage ? " · histórico ↓" : " · histórico completo"}
        </span>
        {activeGroup != null && (
          <span className="chip" style={{ color: "var(--accent)", borderColor: "var(--accent)", fontSize: 10.5 }}>
            📁 {activeGroup.name}
          </span>
        )}
        <span className="sep" />
        <input
          className="input"
          style={{ minWidth: 190, fontFamily: "var(--font-mono)" }}
          placeholder="⌕ buscar en todo el histórico…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <NodeSelect value={nodeFilter} onChange={setNodeFilter} options={summaries} placeholder="— todos los nodos —" />
        <select className="input" value={gatewayFilter} onChange={(e) => setGatewayFilter(e.target.value)}>
          <option value="">— todas las pasarelas —</option>
          {gatewayIds.map((g) => (
            <option key={g} value={g}>{g}</option>
          ))}
        </select>
        <select className="input" value={batchFilter} onChange={(e) => setBatchFilter(e.target.value)}>
          <option value="">— todos los lotes —</option>
          {batchIds.map((b) => (
            <option key={b} value={b}>Lote #{b}</option>
          ))}
        </select>
        <span className="seg">
          {ALL_CATEGORIES.map((c) => (
            <button
              key={c}
              className={categories.has(c) ? "on" : undefined}
              style={categories.has(c) ? { color: CATEGORY_COLOR[c], background: `color-mix(in srgb, ${CATEGORY_COLOR[c]} 12%, transparent)` } : undefined}
              onClick={() => toggleCategory(c)}
              title={`Mostrar/ocultar eventos de tipo ${CATEGORY_LABEL[c]}`}
            >
              {CATEGORY_LABEL[c]}
            </button>
          ))}
        </span>
        <span style={{ marginLeft: "auto" }} />
        <button
          className={`btn ghost${groupBursts ? " on" : ""}`}
          style={groupBursts ? { color: "var(--accent)", borderColor: "var(--accent)" } : undefined}
          onClick={() => setGroupBursts(!groupBursts)}
          title={
            "Agrupar ráfagas repetitivas.\n\n" +
            "Activado: 3 o más paquetes SEGUIDOS del mismo nodo y del mismo tipo " +
            "(p. ej. 12 telemetrías una tras otra) se pliegan en una sola línea " +
            "«×12 Telemetría · nodo» — clic en ella para ver las entradas una a una.\n\n" +
            "Es solo presentación: cada paquete sigue siendo su propia entrada en el " +
            "histórico, no se fusiona ni se pierde nada. Si entre medias llega un " +
            "paquete de otro nodo u otro tipo, la ráfaga se corta.\n\n" +
            "Desactivado: todo plano, una línea por paquete."
          }
        >
          {groupBursts ? "◉" : "○"} ráfagas
        </button>
      </div>

      {/* Resumen de tráfico reciente: último minuto, en memoria */}
      <div className="toolbar" style={{ gap: "1rem", flexWrap: "wrap", paddingTop: 0 }}>
        <span className="microlabel" style={{ color: "var(--text-faint)" }}>
          Últimos 60 s
        </span>
        {PACKET_FILTERS.map((f) => (
          <span key={f.key} className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>
            <span style={{ color: f.color }}>{f.label}</span> {recentCounts.get(f.key) ?? 0}
          </span>
        ))}
      </div>

      {/* Filtros rápidos por tipo de paquete */}
      <div className="toolbar" style={{ paddingTop: 0 }}>
        <span className="seg">
          <button
            className={packetFilter === "" ? "on" : undefined}
            onClick={() => setPacketFilter("")}
            title="Mostrar todos los tipos de paquete"
          >
            Todos
          </button>
          {PACKET_FILTERS.map((f) => (
            <button
              key={f.key}
              className={packetFilter === f.key ? "on" : undefined}
              style={
                packetFilter === f.key
                  ? { color: f.color, background: `color-mix(in srgb, ${f.color} 12%, transparent)` }
                  : undefined
              }
              onClick={() => setPacketFilter(packetFilter === f.key ? "" : f.key)}
              title={`Mostrar solo ${f.label}`}
            >
              {f.label}
            </button>
          ))}
        </span>
      </div>

      {/* Terminal de eventos (más recientes arriba; el fondo carga histórico) */}
      <div className="ws-scroll" ref={scrollRef} onScroll={onScroll} style={{ position: "relative" }}>
        {scrolledAway && pendingCount > 0 && (
          <button
            onClick={backToLive}
            style={{
              position: "sticky",
              top: 8,
              left: "50%",
              transform: "translateX(-50%)",
              zIndex: 5,
              background: "var(--accent)",
              color: "#fff",
              border: "none",
              borderRadius: 12,
              padding: "0.2rem 0.8rem",
              fontSize: 11.5,
              cursor: "pointer",
              boxShadow: "0 2px 8px rgba(0,0,0,.4)",
            }}
          >
            ↑ {pendingCount} evento{pendingCount !== 1 ? "s" : ""} nuevo{pendingCount !== 1 ? "s" : ""}
          </button>
        )}
        {history.isLoading ? (
          <div className="empty">Cargando histórico…</div>
        ) : filtered.length === 0 ? (
          <div className="empty">
            {debouncedSearch
              ? "Nada en el histórico coincide con la búsqueda."
              : "Ningún evento coincide con los filtros actuales."}
          </div>
        ) : (
          <div className="termlog" style={{ padding: "0.3rem 0" }}>
            {rows.map((row) =>
              row.kind === "entry" ? (
                <Line
                  key={row.entry.id}
                  e={row.entry}
                  expanded={expanded.has(row.entry.id)}
                  onToggle={() => toggleExpanded(row.entry.id)}
                />
              ) : (
                <BurstLine
                  key={row.key}
                  entries={row.entries}
                  expanded={expandedBursts.has(row.key)}
                  onToggle={() => toggleBurst(row.key)}
                  expandedEntries={expanded}
                  onToggleEntry={toggleExpanded}
                />
              ),
            )}
            {history.isFetchingNextPage && (
              <div style={{ color: "var(--text-faint)", fontSize: 11.5, padding: "0.4rem 0.75rem" }}>
                Cargando más histórico…
              </div>
            )}
            {!history.hasNextPage && (
              <div style={{ color: "var(--text-faint)", fontSize: 11.5, padding: "0.4rem 0.75rem" }}>
                — principio del histórico —
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** Ráfaga plegada: N entradas iguales seguidas, expandible a sus entradas. */
function BurstLine({
  entries,
  expanded,
  onToggle,
  expandedEntries,
  onToggleEntry,
}: {
  entries: ActivityEntry[];
  expanded: boolean;
  onToggle: () => void;
  expandedEntries: Set<string>;
  onToggleEntry: (id: string) => void;
}) {
  const first = entries[0];
  const last = entries[entries.length - 1];
  const identity = packetColor(first.packetType);
  return (
    <>
      <div
        className="line"
        style={{ borderLeftColor: identity ?? "var(--text-faint)", cursor: "pointer" }}
        onClick={onToggle}
        title={expanded ? "Plegar la ráfaga" : "Expandir las entradas individuales"}
      >
        <span className="ts">{first.time}</span>
        <span style={{ fontSize: 12 }}>{expanded ? "▾" : "▸"}</span>
        <span
          className="msg mono"
          style={{
            color: identity ?? "var(--text-dim)",
            background: `color-mix(in srgb, ${identity ?? "var(--text-faint)"} 12%, transparent)`,
            borderRadius: 8,
            padding: "0 0.45rem",
            fontSize: 11,
          }}
        >
          ×{entries.length}
        </span>
        <span className="msg" style={{ color: identity ?? "var(--text-dim)" }}>
          {first.packetType} · {first.nodeLabel ?? first.nodeId}
        </span>
        <span className="msg" style={{ color: "var(--text-faint)", fontSize: 11 }}>
          {last.time.split(".")[0]} → {first.time.split(".")[0]}
        </span>
      </div>
      {expanded &&
        entries.map((e) => (
          <Line key={e.id} e={e} expanded={expandedEntries.has(e.id)} onToggle={() => onToggleEntry(e.id)} indent />
        ))}
    </>
  );
}

/** Una entrada del Registro (un paquete o un hecho), con su capa técnica. */
function Line({
  e,
  expanded,
  onToggle,
  indent,
}: {
  e: ActivityEntry;
  expanded: boolean;
  onToggle: () => void;
  indent?: boolean;
}) {
  const identity = packetColor(e.packetType);
  const accent = identity ?? (e.priority ? PRIORITY_COLOR[e.priority] : CATEGORY_COLOR[e.category]);
  const hasTechnical = e.internalType != null || e.rssi != null || e.snr != null || e.raw != null;
  const originDest = originDestination(e);
  const extraDetails = e.details?.filter(([k]) => k !== "Destinatario" && k !== "Canal") ?? [];
  return (
    <div className="line" style={{ borderLeftColor: accent, marginLeft: indent ? 18 : undefined }}>
      <span className="ts">{e.time}</span>
      {e.icon && <span style={{ fontSize: 12, lineHeight: "1.4" }}>{e.icon}</span>}
      {e.gatewayId && (
        <span className="src" title={`Pasarela de origen: ${e.gatewayId}`}>{e.gatewayId}</span>
      )}
      <span style={{ display: "inline-flex", flexDirection: "column", gap: 1 }}>
        <span
          className="msg"
          style={{
            color: identity ?? (e.priority ? accent : SEVERITY_COLOR[e.severity]),
            fontWeight: e.priority === "critical" || e.priority === "important" ? 600 : 400,
          }}
        >
          {e.text}
        </span>
        {originDest ? (
          <span className="msg" style={{ color: "var(--text-dim)", fontSize: 11 }}>
            Origen: <span style={{ color: "var(--text)" }}>{originDest.origin}</span>
            {"  ·  "}
            Destino: <span style={{ color: "var(--text)" }}>{originDest.destination}</span>
          </span>
        ) : (
          e.nodeLabel && <span className="msg" style={{ color: "var(--text-dim)" }}>{e.nodeLabel}</span>
        )}
        {e.description && (
          <span className="msg" style={{ color: "var(--text)", fontStyle: "italic" }}>{e.description}</span>
        )}
        {extraDetails.length > 0 && (
          <span className="msg" style={{ color: "var(--text-faint)", fontSize: 11 }}>
            {extraDetails.map(([k, v], i) => (
              <span key={k}>
                {i > 0 && " · "}
                {k}: <span style={{ color: "var(--text-dim)" }}>{v}</span>
              </span>
            ))}
          </span>
        )}
        {hasTechnical && (
          <>
            <button
              className="btn ghost"
              style={{ alignSelf: "flex-start", fontSize: 10, padding: "0 0.4rem", height: 16 }}
              onClick={onToggle}
            >
              {expanded ? "▾ Ocultar paquete" : "▸ Ver paquete"}
            </button>
            {expanded && (
              <span className="msg mono" style={{ color: "var(--text-faint)", fontSize: 10.5, whiteSpace: "pre-wrap" }}>
                {[
                  e.internalType && `Tipo interno: ${e.internalType}`,
                  e.rssi != null && `RSSI: ${e.rssi} dBm`,
                  e.snr != null && `SNR: ${e.snr} dB`,
                  e.raw && JSON.stringify(e.raw, null, 2),
                ]
                  .filter(Boolean)
                  .join("\n")}
              </span>
            )}
          </>
        )}
      </span>
    </div>
  );
}

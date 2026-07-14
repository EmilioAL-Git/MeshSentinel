import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { type ActivityEntry } from "../../activity";
import { fetchChatChannels, fetchChatMessages, type GatewayOut, type NodeSummaryOut } from "../../api/client";
import { channelLabel, chatRowFromActivity, chatRowFromApi, contentKey, initials, type ChatRow } from "../../chat";
import { NodeSelect } from "../NodeSelect";

/**
 * Chat: monitor profesional de las conversaciones de la red — no una app de
 * mensajería. Cada paquete TEXT_MESSAGE_APP es una fila, cronológica,
 * siempre (sin burbujas, sin agrupar por conversación).
 *
 * Reutiliza el mismo paquete que Actividad: el stream en vivo se deriva de
 * `entries` (el buffer WS que ya mantiene App, narrado por el backend);
 * el histórico paginado usa `/chat/messages` (tabla propia — necesaria para
 * filtrar por canal/DM con columnas reales, cosa que el JSON de Actividad
 * no ofrece). Fusión con dedupe por CONTENIDO (`contentKey` en chat.ts), no
 * por id ni por tiempo: el histórico SÍ solapa con el vivo — TanStack Query
 * refetchea la página 1 al recuperar el foco, el fetch inicial puede
 * resolverse después de que un mensaje llegue por WS, y la siembra del
 * buffer de Actividad al recargar trae los mismos mensajes que el
 * histórico. Ni el event_id (espacios distintos: envelope narrado vs. PK)
 * ni el timestamp (el activity.event se timestampea al emitirse, la fila al
 * ingerir el envelope del gateway — difieren en ms) sirven de clave.
 */

const PAGE_SIZE = 100;

type ChannelTab = "all" | "dm" | number;

export function ChatConsole({
  entries,
  summaries,
  gateways,
}: {
  entries: ActivityEntry[];
  summaries: NodeSummaryOut[];
  gateways: GatewayOut[];
}) {
  const nodeNames = useMemo(() => {
    const map = new Map<string, string>();
    for (const s of summaries) {
      const name = s.node.long_name ?? s.node.short_name;
      if (name) map.set(s.node.node_id, name);
    }
    return map;
  }, [summaries]);

  const [channelTab, setChannelTab] = useState<ChannelTab>("all");
  const [nodeFilter, setNodeFilter] = useState("");
  const [gatewayFilter, setGatewayFilter] = useState("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 350);
    return () => window.clearTimeout(timer);
  }, [search]);

  const serverFilters = useMemo(
    () => ({
      channelIndex: typeof channelTab === "number" ? channelTab : undefined,
      dmOnly: channelTab === "dm" || undefined,
      // Un DM también lleva channel_index: al filtrar por un canal concreto
      // hay que excluir los DM que compartan ese índice explícitamente.
      broadcastOnly: typeof channelTab === "number" || undefined,
      nodeId: nodeFilter || undefined,
      gatewayId: gatewayFilter || undefined,
      q: debouncedSearch || undefined,
    }),
    [channelTab, nodeFilter, gatewayFilter, debouncedSearch],
  );

  const channelsQuery = useQuery({ queryKey: ["chat-channels"], queryFn: fetchChatChannels });

  const history = useInfiniteQuery({
    queryKey: ["chat-messages", serverFilters],
    queryFn: ({ pageParam }) => fetchChatMessages(PAGE_SIZE, { ...serverFilters, beforeId: pageParam }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => (last.length === PAGE_SIZE ? last[last.length - 1].id : undefined),
  });

  const historyRows = useMemo(() => {
    const out: ChatRow[] = [];
    for (const page of history.data?.pages ?? []) {
      for (const m of page) out.push(chatRowFromApi(m));
    }
    return out;
  }, [history.data]);

  const matchesFilters = useMemo(() => {
    const needle = debouncedSearch.toLowerCase();
    return (row: ChatRow): boolean => {
      if (channelTab === "dm" && !row.toNodeId) return false;
      if (channelTab !== "dm" && channelTab !== "all" && row.toNodeId) return false;
      if (typeof channelTab === "number" && row.channelIndex !== channelTab) return false;
      if (nodeFilter && row.fromNodeId !== nodeFilter && row.toNodeId !== nodeFilter) return false;
      if (gatewayFilter && row.gatewayId !== gatewayFilter) return false;
      if (needle) {
        const haystack = [row.text, row.fromNodeId, nodeNames.get(row.fromNodeId) ?? ""]
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      return true;
    };
  }, [channelTab, nodeFilter, gatewayFilter, debouncedSearch, nodeNames]);

  const liveRows = useMemo(() => {
    const out: ChatRow[] = [];
    for (const e of entries) {
      const row = chatRowFromActivity(e);
      if (row && matchesFilters(row)) out.push(row);
    }
    return out;
  }, [entries, matchesFilters]);

  const rows = useMemo(() => {
    // Dedupe vivo↔histórico por contenido (ver comentario de cabecera):
    // la fila del histórico gana (trae channel_name y direction reales).
    const known = new Set(historyRows.map(contentKey));
    const merged = [
      ...liveRows.filter((row) => !known.has(contentKey(row))),
      ...historyRows.filter(matchesFilters),
    ];
    merged.sort((a, b) => b.receivedAtMs - a.receivedAtMs);
    return merged;
  }, [liveRows, historyRows, matchesFilters]);

  const gatewayIds = useMemo(() => gateways.map((g) => g.gateway_id).sort(), [gateways]);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    if (
      el.scrollHeight - el.scrollTop - el.clientHeight < 400 &&
      history.hasNextPage &&
      !history.isFetchingNextPage
    ) {
      void history.fetchNextPage();
    }
  };

  const channels = channelsQuery.data?.channels ?? [];
  const dmCount = channelsQuery.data?.dm_count ?? 0;

  return (
    <div className="ws">
      <div className="toolbar">
        <span className="microlabel">Chat</span>
        <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>
          {rows.length} mensajes{history.hasNextPage ? " · histórico ↓" : " · histórico completo"}
        </span>
        <span className="sep" />
        <span className="seg">
          <button className={channelTab === "all" ? "on" : undefined} onClick={() => setChannelTab("all")}>
            Todos
          </button>
          {channels.map((c) => (
            <button
              key={c.channel_index}
              className={channelTab === c.channel_index ? "on" : undefined}
              onClick={() => setChannelTab(c.channel_index)}
              title={`${c.message_count} mensajes`}
            >
              {c.channel_name ?? `Canal ${c.channel_index}`}
            </button>
          ))}
          {dmCount > 0 && (
            <button className={channelTab === "dm" ? "on" : undefined} onClick={() => setChannelTab("dm")}>
              Directos
            </button>
          )}
        </span>
      </div>

      <div className="toolbar" style={{ paddingTop: 0 }}>
        <input
          className="input"
          style={{ minWidth: 190, fontFamily: "var(--font-mono)" }}
          placeholder="⌕ buscar texto, nodo…"
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
      </div>

      <div className="ws-scroll" ref={scrollRef} onScroll={onScroll}>
        {rows.length === 0 && (
          <div className="mono" style={{ padding: "1.5rem", color: "var(--text-faint)", fontSize: 12 }}>
            {history.isLoading ? "Cargando…" : "Sin mensajes con estos filtros."}
          </div>
        )}
        {rows.map((row) => (
          <ChatRowView key={row.id} row={row} nodeNames={nodeNames} />
        ))}
        {history.hasNextPage && (
          <div style={{ padding: "0.75rem", textAlign: "center" }}>
            <button
              className="btn ghost"
              disabled={history.isFetchingNextPage}
              onClick={() => history.fetchNextPage()}
            >
              {history.isFetchingNextPage ? "Cargando…" : "Cargar más"}
            </button>
          </div>
        )}
        {!history.hasNextPage && rows.length > 0 && (
          <div className="mono" style={{ padding: "0.75rem", textAlign: "center", color: "var(--text-faint)", fontSize: 10.5 }}>
            — principio del histórico —
          </div>
        )}
      </div>
    </div>
  );
}

function ChatRowView({ row, nodeNames }: { row: ChatRow; nodeNames: Map<string, string> }) {
  const name = nodeNames.get(row.fromNodeId) ?? row.fromNodeId;
  const toName = row.toNodeId ? (nodeNames.get(row.toNodeId) ?? row.toNodeId) : null;
  return (
    <div
      className="mono"
      style={{
        display: "grid",
        gridTemplateColumns: "28px 1fr auto",
        columnGap: "0.6rem",
        padding: "0.4rem 0.9rem",
        borderBottom: "1px solid var(--border-faint, rgba(255,255,255,0.06))",
        alignItems: "start",
      }}
    >
      <div
        className="mono"
        style={{
          width: 28,
          height: 28,
          borderRadius: "50%",
          background: "color-mix(in srgb, var(--accent) 18%, transparent)",
          color: "var(--accent)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 10.5,
          fontWeight: 600,
        }}
        title={row.fromNodeId}
      >
        {initials(name)}
      </div>
      <div>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "baseline", flexWrap: "wrap" }}>
          <span style={{ fontWeight: 600, fontSize: 12.5 }}>{name}</span>
          <span style={{ fontSize: 10.5, color: "var(--text-faint)" }}>{row.time}</span>
          <span
            className="chip"
            style={{
              fontSize: 9.5,
              color: row.toNodeId ? "var(--accent)" : "var(--text-dim)",
              borderColor: row.toNodeId ? "var(--accent)" : undefined,
            }}
          >
            {channelLabel(row)}
          </span>
          {toName && (
            <span style={{ fontSize: 10.5, color: "var(--text-faint)" }}>→ {toName}</span>
          )}
        </div>
        <div style={{ fontSize: 12.5, color: "var(--text)", marginTop: 2, wordBreak: "break-word" }}>
          {row.text}
        </div>
      </div>
      <div style={{ textAlign: "right", fontSize: 10, color: "var(--text-faint)", whiteSpace: "nowrap" }}>
        {row.rssi != null && <div>{row.rssi} dBm</div>}
        {row.snr != null && <div>SNR {row.snr.toFixed(1)}</div>}
        {row.gatewayId && <div>{row.gatewayId}</div>}
        <div style={{ color: "var(--ok)" }}>{row.direction === "inbound" ? "Recibido" : row.direction}</div>
      </div>
    </div>
  );
}

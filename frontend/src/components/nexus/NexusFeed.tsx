import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchNexusConversation,
  type NexusConversationMessageOut,
  type NexusOperationOut,
} from "../../api/client";
import { STATUS_COLORS, STATUS_LABELS } from "./NexusOperationsPanel";
import { t } from "../../tokens";

type Item =
  | { kind: "op"; at: number; key: string; op: NexusOperationOut }
  | { kind: "msg"; at: number; key: string; msg: NexusConversationMessageOut };

const OUTCOME_STYLE = {
  ok: { icon: "✓", color: "var(--ok)" },
  error: { icon: "✗", color: "var(--crit)" },
  info: { icon: "ℹ", color: "var(--accent)" },
} as const;

const clock = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString("es-ES", { hour12: false }) : "--:--:--";

function targetText(op: NexusOperationOut): string {
  switch (op.target_kind) {
    case "broadcast":
      return "toda la malla Nexus";
    case "local":
      return "nodo local";
    default:
      return `${op.target_kind} ${op.target_value ?? ""}`.trim();
  }
}

/**
 * Chat del canal Nexus: lo que mandamos (burbujas propias), lo que oímos
 * (texto crudo del nodo) y, debajo de cada respuesta reconocida, su
 * interpretación en lenguaje de operador. Solo lectura — enviar se hace
 * desde el compositor de la consola.
 */
export function NexusFeed({ showRaw, showNoise }: { showRaw: boolean; showNoise: boolean }) {
  const query = useQuery({
    queryKey: ["nexus-conversation"],
    queryFn: () => fetchNexusConversation(),
    refetchInterval: 3000,
  });

  const items = useMemo<Item[]>(() => {
    const data = query.data;
    if (!data) return [];
    const out: Item[] = [];
    for (const op of data.operations) {
      const iso = op.sent_at ?? op.created_at;
      if (iso) out.push({ kind: "op", at: Date.parse(iso), key: `op${op.id}`, op });
    }
    for (const msg of data.messages) {
      if (!showNoise && msg.context_op_id == null && msg.interpretation == null) continue;
      if (msg.received_at) out.push({ kind: "msg", at: Date.parse(msg.received_at), key: `m${msg.id}`, msg });
    }
    return out.sort((a, b) => a.at - b.at || a.key.localeCompare(b.key));
  }, [query.data, showNoise]);

  // Resumen por comando enviado a varios nodos: cuántos respondieron y cómo.
  const rollup = useMemo(() => {
    const m = new Map<number, { total: number; ok: number; error: number }>();
    for (const msg of query.data?.messages ?? []) {
      if (msg.context_op_id == null) continue;
      const r = m.get(msg.context_op_id) ?? { total: 0, ok: 0, error: 0 };
      r.total++;
      if (msg.interpretation?.outcome === "ok") r.ok++;
      if (msg.interpretation?.outcome === "error") r.error++;
      m.set(msg.context_op_id, r);
    }
    return m;
  }, [query.data]);

  const multiGateway = useMemo(
    () => new Set((query.data?.messages ?? []).map((m) => m.gateway_id)).size > 1,
    [query.data],
  );

  // Pegado al fondo mientras el operador no se aleje; si se aleja, no se
  // mueve el scroll bajo sus pies y aparece "↓ nuevos".
  const scrollRef = useRef<HTMLDivElement>(null);
  const [stuck, setStuck] = useState(true);
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stuck) el.scrollTop = el.scrollHeight;
  }, [items.length, stuck]);

  const noChannels = query.data && query.data.channels.length === 0;

  return (
    <div style={{ position: "relative", flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <div
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          setStuck(el.scrollHeight - el.scrollTop - el.clientHeight < 60);
        }}
        style={{ flex: 1, overflowY: "auto", padding: "10px 14px", display: "flex", flexDirection: "column", gap: 6 }}
      >
        {query.isLoading && <div className="empty">Cargando el canal Nexus…</div>}
        {query.isError && <div className="empty" style={{ color: "var(--crit)" }}>No se pudo leer el canal Nexus.</div>}
        {noChannels && (
          <div className="empty">
            Ninguna pasarela tiene un canal llamado «Nexus» o «JenT» configurado: aún no hay conversación que mostrar.
          </div>
        )}
        {query.data && !noChannels && items.length === 0 && (
          <div className="empty">Canal en silencio. Lo que se envíe y lo que respondan los nodos aparecerá aquí.</div>
        )}
        {items.map((it) =>
          it.kind === "op" ? (
            <OpBubble key={it.key} op={it.op} rollup={rollup.get(it.op.id)} />
          ) : (
            <MsgBubble key={it.key} msg={it.msg} showRaw={showRaw} showGateway={multiGateway} />
          ),
        )}
      </div>
      {!stuck && (
        <button
          className="btn"
          style={{ position: "absolute", right: 18, bottom: 10 }}
          onClick={() => {
            setStuck(true);
            const el = scrollRef.current;
            if (el) el.scrollTop = el.scrollHeight;
          }}
        >
          ↓ al final
        </button>
      )}
    </div>
  );
}

function OpBubble({ op, rollup }: { op: NexusOperationOut; rollup?: { total: number; ok: number; error: number } }) {
  const fanout = op.target_kind === "broadcast" || op.target_kind === "group";
  return (
    <div style={{ alignSelf: "flex-end", maxWidth: "78%", display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2 }}>
      <div style={{ fontSize: 10.5, color: t.textFaint }}>
        {clock(op.sent_at ?? op.created_at)} · {op.created_by ?? "sistema"} → {targetText(op)}
        {op.destructive && <span style={{ color: "var(--crit)" }}> · destructivo</span>}
      </div>
      <div
        className="mono"
        style={{
          background: "var(--surface-2)",
          border: "1px solid var(--accent)",
          borderRadius: "8px 8px 2px 8px",
          padding: "5px 10px",
          fontSize: 12.5,
        }}
      >
        {op.text}
      </div>
      <div style={{ fontSize: 10.5, color: STATUS_COLORS[op.status] }}>
        {STATUS_LABELS[op.status]}
        {fanout && rollup && (
          <span style={{ color: t.textDim }}>
            {" "}· {rollup.total} respuesta{rollup.total === 1 ? "" : "s"}
            {rollup.ok > 0 && ` · ${rollup.ok} correcta${rollup.ok === 1 ? "" : "s"}`}
            {rollup.error > 0 && ` · ${rollup.error} con error`}
          </span>
        )}
      </div>
    </div>
  );
}

function MsgBubble({
  msg,
  showRaw,
  showGateway,
}: {
  msg: NexusConversationMessageOut;
  showRaw: boolean;
  showGateway: boolean;
}) {
  const interp = msg.interpretation;
  const style = interp ? OUTCOME_STYLE[interp.outcome] : null;
  const hideRaw = interp != null && !showRaw;
  return (
    <div style={{ alignSelf: "flex-start", maxWidth: "82%", display: "flex", flexDirection: "column", gap: 2 }}>
      <div style={{ fontSize: 10.5, color: t.textFaint }}>
        <strong style={{ color: t.textDim }}>{msg.sender_label}</strong> · {clock(msg.received_at)}
        {showGateway && msg.gateway_id && <> · {msg.gateway_id}</>}
        {msg.snr != null && <> · SNR {msg.snr}</>}
        {msg.hops_away != null && <> · {msg.hops_away} salto{msg.hops_away === 1 ? "" : "s"}</>}
        {msg.parts > 1 && <> · respuesta completa ({msg.parts} mensajes unidos)</>}
      </div>
      <div
        style={{
          background: "var(--surface)",
          border: `1px solid ${style ? style.color : "var(--border-subtle)"}`,
          borderRadius: "8px 8px 8px 2px",
          padding: "5px 10px",
        }}
      >
        {interp && style && (
          <div style={{ color: style.color, fontSize: 13 }}>
            {style.icon} {msg.sender_label.split(" (")[0]}: {interp.summary}
          </div>
        )}
        {!hideRaw && (
          <div className="mono" style={{ fontSize: 12, color: interp ? t.textFaint : undefined, whiteSpace: "pre-wrap" }}>
            {msg.text}
          </div>
        )}
      </div>
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { originDestination, toEntry, type ActivityEntry } from "../../activity";
import { fetchActivityLog, type ActivityLogItemOut } from "../../api/client";
import { t } from "../../tokens";

/**
 * Pestaña Log del Inspector: el registro de TODOS los paquetes/hechos del
 * nodo, servido por el Registro persistente (`GET /activity?node_id=`) —
 * antes filtraba el buffer efímero de la sesión y solía estar vacío.
 * Mismo formato de tarjeta que la consola del Centro (hora + tipo + info
 * del paquete); clic = desplegable con la vista "bonita" (datos extraídos)
 * y el JSON puro tal como se persistió.
 */

const SEVERITY_COLOR: Record<ActivityEntry["severity"], string> = {
  info: t.border,
  ok: t.ok,
  warn: t.warn,
  error: t.crit,
};

interface LogItem {
  entry: ActivityEntry;
  /** Payload completo persistido — la fuente del "JSON puro". */
  payload: Record<string, unknown>;
}

function toItems(items: ActivityLogItemOut[]): LogItem[] {
  const out: LogItem[] = [];
  for (const it of items) {
    const entry = toEntry(it);
    if (entry) out.push({ entry, payload: it.payload });
  }
  return out;
}

export function NodeLog({ nodeId }: { nodeId: string }) {
  const log = useQuery({
    queryKey: ["node-activity", nodeId],
    queryFn: () => fetchActivityLog(150, { nodeId }),
    refetchInterval: 10_000,
  });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [jsonOpen, setJsonOpen] = useState<Set<string>>(new Set());

  const toggle = (set: Set<string>, id: string, apply: (s: Set<string>) => void) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    apply(next);
  };

  const items = toItems(log.data ?? []);

  if (log.isLoading) return <div style={{ color: t.textFaint, fontSize: 12 }}>Cargando registro…</div>;
  if (log.isError)
    return <div style={{ color: t.crit, fontSize: 12 }}>Error consultando el registro del nodo.</div>;
  if (items.length === 0)
    return <div style={{ color: t.textFaint, fontSize: 12 }}>Sin paquetes registrados para este nodo todavía.</div>;

  return (
    <>
      {items.map(({ entry: e, payload }) => {
        const isOpen = expanded.has(e.id);
        const summary =
          e.details && e.details.length > 0
            ? e.details.map(([k, v]) => `${k}: ${v}`).join(" · ")
            : e.description ?? null;
        const originDest = originDestination(e);
        return (
          <div
            key={e.id}
            onClick={() => toggle(expanded, e.id, setExpanded)}
            style={{
              border: `1px solid ${t.borderSubtle}`,
              borderLeft: `2px solid ${SEVERITY_COLOR[e.severity]}`,
              borderRadius: 5,
              padding: "0.3rem 0.55rem",
              marginBottom: 4,
              fontSize: 12,
              lineHeight: 1.35,
              background: t.surface,
              cursor: "pointer",
            }}
            title={isOpen ? undefined : "Clic para ver toda la información"}
          >
            {/* Línea 1: hora + icono + tipo de paquete/hecho */}
            <div style={{ display: "flex", alignItems: "baseline", gap: 6, minWidth: 0 }}>
              <span style={{ fontFamily: t.fontMono, color: t.textFaint, fontSize: 11, flexShrink: 0 }}>
                {e.time.split(".")[0]}
              </span>
              {e.icon && <span style={{ fontSize: 11, flexShrink: 0 }}>{e.icon}</span>}
              <span
                style={{
                  color: t.text,
                  fontWeight: 600,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {e.packetType ?? e.text}
              </span>
              {e.gatewayId && (
                <span style={{ color: t.textFaint, fontFamily: t.fontMono, fontSize: 10.5, flexShrink: 0 }}>
                  {e.gatewayId}
                </span>
              )}
              <span style={{ color: t.textFaint, fontSize: 10, marginLeft: "auto", flexShrink: 0 }}>
                {isOpen ? "▾" : "▸"}
              </span>
            </div>
            {/* Línea 2: la información del paquete */}
            {summary && <div style={{ color: t.textDim, marginTop: 2 }}>{summary}</div>}

            {isOpen && (
              <div
                onClick={(ev) => ev.stopPropagation()}
                style={{
                  margin: "0.35rem 0 0.1rem",
                  padding: "0.4rem 0.55rem",
                  background: t.surface2,
                  borderRadius: 4,
                  fontSize: 11.5,
                  cursor: "default",
                }}
              >
                {/* Vista "bonita": los datos ya extraídos y redactados */}
                {e.description && (
                  <div style={{ color: t.textDim, fontStyle: "italic", marginBottom: 4 }}>{e.description}</div>
                )}
                {originDest && (
                  <div style={{ color: t.textDim, marginBottom: 4 }}>
                    Origen: <span style={{ color: t.text }}>{originDest.origin}</span> · Destino:{" "}
                    <span style={{ color: t.text }}>{originDest.destination}</span>
                  </div>
                )}
                {(e.details ?? []).map(([k, v]) => (
                  <div key={k} style={{ display: "flex", gap: 8 }}>
                    <span style={{ color: t.textFaint, minWidth: 110 }}>{k}</span>
                    <span style={{ color: t.text, fontFamily: t.fontMono }}>{v}</span>
                  </div>
                ))}
                {(e.internalType != null || e.snr != null || e.rssi != null) && (
                  <div style={{ color: t.textFaint, fontFamily: t.fontMono, fontSize: 11, marginTop: 4 }}>
                    {e.internalType && <>{e.internalType}</>}
                    {e.internalType && (e.snr != null || e.rssi != null) && " · "}
                    {e.snr != null && <>SNR {e.snr} dB</>}
                    {e.snr != null && e.rssi != null && " · "}
                    {e.rssi != null && <>RSSI {e.rssi} dBm</>}
                  </div>
                )}

                {/* JSON puro: el payload completo tal como se persistió */}
                <button
                  className="btn ghost"
                  style={{ marginTop: 6, fontSize: 10.5, padding: "0.1rem 0.5rem" }}
                  onClick={() => toggle(jsonOpen, e.id, setJsonOpen)}
                >
                  {jsonOpen.has(e.id) ? "▾ Ocultar JSON" : "▸ Ver JSON"}
                </button>
                {jsonOpen.has(e.id) && (
                  <pre
                    style={{
                      margin: "5px 0 0",
                      padding: "0.45rem 0.55rem",
                      background: t.bg,
                      border: `1px solid ${t.borderSubtle}`,
                      borderRadius: 4,
                      color: t.textDim,
                      fontFamily: t.fontMono,
                      fontSize: 10.5,
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                      maxHeight: 260,
                      overflowY: "auto",
                    }}
                  >
                    {JSON.stringify(payload, null, 2)}
                  </pre>
                )}
              </div>
            )}
          </div>
        );
      })}
    </>
  );
}

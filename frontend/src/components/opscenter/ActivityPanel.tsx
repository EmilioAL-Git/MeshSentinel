import { useMemo, useState, type CSSProperties } from "react";
import { originDestination, type ActivityCategory, type ActivityEntry } from "../../activity";
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

/** Un paquete sin contenido narrable (sin detalles ni descripción) no aporta
 * nada en la consola compacta del Centro — se omite AQUÍ; la vista Registro
 * (investigación) los sigue mostrando todos. */
function isEmptyPacket(e: ActivityEntry): boolean {
  return e.packetType != null && (e.details?.length ?? 0) === 0 && !e.description;
}

export function ActivityPanel({
  entries,
  focusId,
  focusLabel,
  selectedId,
  onOpenNode,
  nodeNames,
}: {
  entries: ActivityEntry[];
  focusId: string | null;
  focusLabel: string | null;
  selectedId: string | null;
  onOpenNode: (nodeId: string) => void;
  /** node_id -> nombre completo (long_name), resuelto por el Centro desde la
   * flota ya cargada — la entrada solo trae el nombre corto del backend. */
  nodeNames?: Map<string, string>;
}) {
  const [level, setLevel] = useState<Level>("todo");
  const filtered = useMemo(() => {
    const cats = LEVEL_CATEGORIES[level];
    const base = entries.filter((e) => !isEmptyPacket(e));
    return cats == null ? base : base.filter((e) => cats.has(e.category));
  }, [entries, level]);

  // Focus (§7.3): los eventos del objetivo se MUEVEN a una sección fija
  // arriba (no se duplican); el flujo general continúa debajo, intacto.
  const [focusEntries, restEntries] = useMemo(() => {
    if (!focusId) return [[], filtered] as const;
    const own: ActivityEntry[] = [];
    const rest: ActivityEntry[] = [];
    for (const e of filtered) (e.nodeId === focusId ? own : rest).push(e);
    return [own.slice(0, 8), rest] as const;
  }, [filtered, focusId]);

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
        {focusId && (
          <div style={{ borderBottom: `1px solid ${t.borderSubtle}`, background: t.accentTint, paddingBottom: 3, marginBottom: 3 }}>
            <div style={{ color: t.accent, fontSize: 10, letterSpacing: "0.08em", fontWeight: 600, padding: "0.3rem 0.75rem 0.1rem" }}>
              ◎ FOCUS {focusLabel ?? focusId}
            </div>
            {focusEntries.length === 0 && (
              <div style={{ color: t.textFaint, fontSize: 11.5, padding: "0.1rem 0.75rem 0.25rem" }}>
                Sin eventos recientes del objetivo.
              </div>
            )}
            {focusEntries.map((e) => (
              <Row key={e.id} entry={e} highlight={false} onOpenNode={onOpenNode} nodeNames={nodeNames} />
            ))}
          </div>
        )}
        {restEntries.length === 0 && !focusId && (
          <p style={{ color: t.textFaint, fontSize: 12, padding: "0.5rem 0.75rem", margin: 0 }}>
            Esperando eventos…
          </p>
        )}
        {restEntries.map((e) => (
          <Row
            key={e.id}
            entry={e}
            highlight={e.nodeId != null && e.nodeId === selectedId}
            onOpenNode={onOpenNode}
            nodeNames={nodeNames}
          />
        ))}
      </div>
    </div>
  );
}

function Row({
  entry: e,
  highlight,
  onOpenNode,
  nodeNames,
}: {
  entry: ActivityEntry;
  highlight: boolean;
  onOpenNode: (nodeId: string) => void;
  nodeNames?: Map<string, string>;
}) {
  // Clic en la tarjeta = desplegar más información (los detalles completos,
  // origen/destino, radio…). Abrir el Inspector queda en el nombre del nodo
  // y en el botón del desplegable — el clic genérico ya no navega.
  const [expanded, setExpanded] = useState(false);
  // Información del paquete, ya redactada por el backend:
  // "Temperatura: 26.2 °C · Humedad: 25 % · Presión: 935 hPa"
  const summary =
    e.details && e.details.length > 0
      ? e.details.map(([k, v]) => `${k}: ${v}`).join(" · ")
      : e.description ?? null;
  const originDest = originDestination(e);
  const hasMore =
    (e.details?.length ?? 0) > 0 || e.description != null || originDest != null || e.snr != null || e.rssi != null;
  // Nombre completo del nodo (long_name de la flota); el corto del backend
  // como respaldo si aún no está en la flota cargada.
  const fullName = e.nodeId ? (nodeNames?.get(e.nodeId) ?? e.nodeLabel) : null;
  // Hora al segundo: los milisegundos son para la vista Registro, no aquí
  const time = e.time.split(".")[0];

  return (
    <div
      onClick={() => hasMore && setExpanded((x) => !x)}
      style={{
        borderLeft: `2px solid ${SEVERITY_COLOR[e.severity]}`,
        border: `1px solid ${t.borderSubtle}`,
        borderLeftWidth: 2,
        borderLeftColor: SEVERITY_COLOR[e.severity],
        borderRadius: 5,
        padding: "0.3rem 0.55rem",
        margin: "0 0.5rem 4px 0.4rem",
        fontSize: 12,
        lineHeight: 1.35,
        background: highlight ? t.surface2 : t.surface,
        cursor: hasMore ? "pointer" : "default",
      }}
      title={hasMore && !expanded ? "Clic para ver más información" : undefined}
    >
      {/* Línea 1: hora + icono + nombre completo del nodo (o el suceso) */}
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, minWidth: 0 }}>
        <span style={{ fontFamily: t.fontMono, color: t.textFaint, fontSize: 11, flexShrink: 0 }}>{time}</span>
        {e.icon && <span style={{ fontSize: 11, flexShrink: 0 }}>{e.icon}</span>}
        {fullName && e.nodeId ? (
          <span
            onClick={(ev) => {
              ev.stopPropagation();
              onOpenNode(e.nodeId!);
            }}
            style={{
              color: t.text,
              fontWeight: 600,
              cursor: "pointer",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
            title="Abrir el nodo en el Inspector"
          >
            {fullName}
          </span>
        ) : (
          <span style={{ color: t.textDim, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {e.text}
          </span>
        )}
        {fullName && e.packetType && (
          <span style={{ color: t.textFaint, fontSize: 11, flexShrink: 0 }}>{e.packetType}</span>
        )}
        {hasMore && (
          <span style={{ color: t.textFaint, fontSize: 10, marginLeft: "auto", flexShrink: 0 }}>
            {expanded ? "▾" : "▸"}
          </span>
        )}
      </div>
      {/* Línea 2: la información del paquete */}
      {fullName && summary && (
        <div style={{ color: t.textDim, marginTop: 2 }}>{summary}</div>
      )}
      {fullName && !summary && !e.packetType && (
        <div style={{ color: t.textDim, marginTop: 2 }}>{e.text}</div>
      )}

      {expanded && (
        <div
          style={{
            margin: "0.3rem 0 0.15rem",
            padding: "0.35rem 0.5rem",
            background: t.surface2,
            borderRadius: 4,
            fontSize: 11.5,
          }}
        >
          <div style={{ color: t.text, marginBottom: 3 }}>
            {e.packetType ?? e.text}
            {e.gatewayId && (
              <span style={{ color: t.textFaint, fontFamily: t.fontMono, marginLeft: 6 }}>vía {e.gatewayId}</span>
            )}
          </div>
          {e.description && <div style={{ color: t.textDim, fontStyle: "italic", marginBottom: 3 }}>{e.description}</div>}
          {originDest && (
            <div style={{ color: t.textDim, marginBottom: 3 }}>
              Origen: <span style={{ color: t.text }}>{originDest.origin}</span> · Destino:{" "}
              <span style={{ color: t.text }}>{originDest.destination}</span>
            </div>
          )}
          {(e.details ?? []).map(([k, v]) => (
            <div key={k} style={{ display: "flex", gap: 8 }}>
              <span style={{ color: t.textFaint, minWidth: 96 }}>{k}</span>
              <span style={{ color: t.text, fontFamily: t.fontMono }}>{v}</span>
            </div>
          ))}
          {(e.snr != null || e.rssi != null) && (
            <div style={{ color: t.textFaint, fontFamily: t.fontMono, marginTop: 3 }}>
              {e.snr != null && <>SNR {e.snr} dB</>}
              {e.snr != null && e.rssi != null && " · "}
              {e.rssi != null && <>RSSI {e.rssi} dBm</>}
            </div>
          )}
          {e.nodeId && (
            <button
              className="btn ghost"
              style={{ marginTop: 5, fontSize: 11, padding: "0.1rem 0.5rem" }}
              onClick={(ev) => {
                ev.stopPropagation();
                onOpenNode(e.nodeId!);
              }}
            >
              Abrir en el Inspector →
            </button>
          )}
        </div>
      )}
    </div>
  );
}

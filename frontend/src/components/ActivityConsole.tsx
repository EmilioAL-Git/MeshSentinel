import { useEffect, useMemo, useState } from "react";
import {
  CATEGORY_LABEL,
  originDestination,
  packetColor,
  PACKET_FILTERS,
  type ActivityCategory,
  type ActivityEntry,
  type ActivityPriority,
  type ActivitySeverity,
} from "../activity";
import { type GatewayOut, type NodeSummaryOut } from "../api/client";
import { useGroupNodeIds } from "../context/GroupContext";
import { NodeSelect } from "./NodeSelect";
import { GroupScopeBanner } from "./shell/GroupScopeBanner";

/**
 * Registro (Actividad 2.0): el diario/consola de paquetes de la red. Cada
 * línea es un HECHO o un paquete decodificado, redactado por el backend en
 * lenguaje de operador (nunca protobuf ni estados técnicos), con icono,
 * identidad visual por tipo, origen/destino, hora exacta y detalles ya
 * formateados. Mismos filtros y buffer de 500.
 */

const RECENT_WINDOW_MS = 60_000;

const SEVERITY_COLOR: Record<ActivitySeverity, string> = {
  info: "var(--text-dim)",
  ok: "var(--ok)",
  warn: "var(--warn)",
  error: "var(--crit)",
};

/** Prioridad del diario → color del gutter y del título. */
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

export function ActivityConsole({
  entries,
  summaries,
  gateways,
  onClear,
}: {
  entries: ActivityEntry[];
  summaries: NodeSummaryOut[];
  gateways: GatewayOut[];
  onClear: () => void;
}) {
  const [nodeFilter, setNodeFilter] = useState("");
  const [batchFilter, setBatchFilter] = useState("");
  const [gatewayFilter, setGatewayFilter] = useState("");
  const [categories, setCategories] = useState<Set<ActivityCategory>>(new Set(ALL_CATEGORIES));
  // Filtro rápido por tipo de paquete (pulido §3): "" = todos
  const [packetFilter, setPacketFilter] = useState("");
  // Resumen de tráfico reciente (pulido §5): recalcula la ventana de 60s
  // aunque no lleguen eventos nuevos (los antiguos deben ir cayendo del
  // recuento) — sin buffer propio, solo re-evalúa sobre `entries`.
  const [ticker, setTicker] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setTicker((n) => n + 1), 2000);
    return () => window.clearInterval(id);
  }, []);
  // "Ver paquete": capa técnica plegada por defecto (vista principal 100%
  // humana); un id puede reutilizarse entre renders porque event_id es único
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggleExpanded = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Grupo activo ("Grupo como contexto global"): un evento sin nodo asociado
  // (pasarela, sistema) no se le puede atribuir a ningún grupo — se mantiene
  // siempre visible, igual criterio que en Alertas.
  const groupNodeIds = useGroupNodeIds(summaries);
  const groupScoped = useMemo(
    () => (groupNodeIds == null ? entries : entries.filter((e) => e.nodeId == null || groupNodeIds.has(e.nodeId))),
    [entries, groupNodeIds],
  );

  // Batches vistos en el buffer (para el filtro)
  const batchIds = useMemo(
    () =>
      [...new Set(groupScoped.map((e) => e.batchId).filter((b): b is number => b != null))].sort(
        (a, b) => b - a,
      ),
    [groupScoped],
  );
  const gatewayIds = useMemo(() => {
    const ids = new Set(gateways.map((g) => g.gateway_id));
    // "system": origen de eventos internos del backend (alertas, actividad),
    // no una pasarela real — debe coincidir con SYSTEM_SOURCE en envelopes.py
    for (const e of groupScoped) if (e.gatewayId && e.gatewayId !== "system") ids.add(e.gatewayId);
    return [...ids].sort();
  }, [groupScoped, gateways]);

  // Resumen de tráfico reciente (pulido §5): último minuto, en memoria pura
  // sobre lo que ya está en el buffer del grupo activo — sin SQL, sin
  // histórico. `ticker` fuerza recalcular la ventana aunque no lleguen
  // eventos nuevos (los antiguos deben ir cayendo del recuento).
  const recentCounts = useMemo(() => {
    void ticker;
    const cutoff = Date.now() - RECENT_WINDOW_MS;
    const counts = new Map<string, number>(PACKET_FILTERS.map((f) => [f.key, 0]));
    for (const e of groupScoped) {
      if (!e.packetType || e.receivedAtMs < cutoff) continue;
      const bucket = PACKET_FILTERS.find((f) => f.types.includes(e.packetType!));
      if (bucket) counts.set(bucket.key, (counts.get(bucket.key) ?? 0) + 1);
    }
    return counts;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupScoped, ticker]);

  const filtered = useMemo(
    () =>
      groupScoped.filter(
        (e) =>
          categories.has(e.category) &&
          (nodeFilter === "" || e.nodeId === nodeFilter) &&
          (batchFilter === "" || e.batchId === Number(batchFilter)) &&
          (gatewayFilter === "" || e.gatewayId === gatewayFilter) &&
          (packetFilter === "" ||
            PACKET_FILTERS.find((f) => f.key === packetFilter)?.types.includes(e.packetType ?? "")),
      ),
    [groupScoped, categories, nodeFilter, batchFilter, gatewayFilter, packetFilter],
  );

  const toggleCategory = (c: ActivityCategory) => {
    const next = new Set(categories);
    if (next.has(c)) next.delete(c);
    else next.add(c);
    setCategories(next);
  };

  const hasFilters =
    nodeFilter !== "" ||
    batchFilter !== "" ||
    gatewayFilter !== "" ||
    packetFilter !== "" ||
    categories.size !== ALL_CATEGORIES.length;

  return (
    <div className="ws">
      <GroupScopeBanner shown={groupScoped.length} total={entries.length} label="eventos" />
      <div className="toolbar">
        <span className="microlabel">Registro de eventos</span>
        <span className="noc-pulse" style={{ color: "var(--ok)", fontSize: 9 }}>●</span>
        <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>
          {filtered.length}
          {hasFilters ? `/${entries.length}` : ""} eventos · buffer 500
        </span>
        <span className="sep" />
        <NodeSelect value={nodeFilter} onChange={setNodeFilter} options={summaries} placeholder="— todos los nodos —" />
        <select className="input" value={batchFilter} onChange={(e) => setBatchFilter(e.target.value)}>
          <option value="">— todos los lotes —</option>
          {batchIds.map((b) => (
            <option key={b} value={b}>
              Lote #{b}
            </option>
          ))}
        </select>
        <select className="input" value={gatewayFilter} onChange={(e) => setGatewayFilter(e.target.value)}>
          <option value="">— todas las pasarelas —</option>
          {gatewayIds.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
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
        <button className="btn ghost" onClick={onClear} disabled={entries.length === 0}>
          Limpiar
        </button>
      </div>

      {/* Resumen de tráfico reciente (pulido §5): último minuto, en memoria */}
      <div
        className="toolbar"
        style={{ gap: "1rem", flexWrap: "wrap", paddingTop: 0 }}
      >
        <span className="microlabel" style={{ color: "var(--text-faint)" }}>
          Últimos 60 s
        </span>
        {PACKET_FILTERS.map((f) => (
          <span key={f.key} className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>
            <span style={{ color: f.color }}>{f.label}</span> {recentCounts.get(f.key) ?? 0}
          </span>
        ))}
      </div>

      {/* Filtros rápidos por tipo de paquete (pulido §3) */}
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

      {/* Terminal de eventos (más recientes arriba) */}
      <div className="ws-scroll">
        {filtered.length === 0 ? (
          <div className="empty">
            {entries.length === 0
              ? "Esperando eventos… El registro muestra en tiempo real la actividad del sistema: operaciones remotas (cola → envío → respuesta → verificación), lotes, pasarelas, alertas y tráfico de la malla."
              : "Ningún evento coincide con los filtros actuales."}
          </div>
        ) : (
          <div className="termlog" style={{ padding: "0.3rem 0" }}>
            {filtered.map((e) => {
              // Identidad visual por tipo de paquete (pulido §4): un paquete
              // se identifica por su tipo; un hecho/suceso (sin packetType)
              // sigue coloreándose por severidad, como antes.
              const identity = packetColor(e.packetType);
              const accent = identity ?? (e.priority ? PRIORITY_COLOR[e.priority] : CATEGORY_COLOR[e.category]);
              // Capa técnica: solo existe si el backend la envió (entradas
              // de paquete); nunca se muestra en la cabecera principal.
              const hasTechnical =
                e.internalType != null || e.rssi != null || e.snr != null || e.raw != null;
              const isExpanded = expanded.has(e.id);
              const originDest = originDestination(e);
              // "Destinatario"/"Canal" ya se muestran como Destino arriba —
              // no repetirlos en la lista genérica de detalles
              const extraDetails = e.details?.filter(([k]) => k !== "Destinatario" && k !== "Canal") ?? [];
              return (
                <div key={e.id} className="line" style={{ borderLeftColor: accent }}>
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
                      e.nodeLabel && (
                        <span className="msg" style={{ color: "var(--text-dim)" }}>{e.nodeLabel}</span>
                      )
                    )}
                    {e.description && (
                      <span className="msg" style={{ color: "var(--text)", fontStyle: "italic" }}>
                        {e.description}
                      </span>
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
                          onClick={() => toggleExpanded(e.id)}
                        >
                          {isExpanded ? "▾ Ocultar paquete" : "▸ Ver paquete"}
                        </button>
                        {isExpanded && (
                          <span
                            className="msg mono"
                            style={{ color: "var(--text-faint)", fontSize: 10.5, whiteSpace: "pre-wrap" }}
                          >
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
            })}
          </div>
        )}
      </div>
    </div>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type CSSProperties, type ReactNode } from "react";
import { usePersistedState } from "../../hooks/usePersistedState";
import {
  ackAlert,
  addGroupMember,
  createGroup,
  createOperation,
  createTag,
  fetchGateways,
  fetchGroups,
  fetchNode,
  fetchNodeConfig,
  fetchNodeGateways,
  fetchNodePositions,
  fetchNodeTelemetry,
  fetchTags,
  refreshNodeConfig,
  removeGroupMember,
  retryOperation,
  setNodeFavorite,
  setNodeIgnored,
  setNodePreferredGateway,
  setNodeTags,
  setNodeTypeOverride,
  type AlertOut,
  type NodeSummaryOut,
  type OperationOut,
} from "../../api/client";
import type { ActivityEntry } from "../../activity";
import { relativeTime } from "../../time";
import { alertSeverityColor, chipStyle, t } from "../../tokens";
import { trackOperations } from "../../opTracker";
import { useActiveGroup } from "../../context/GroupContext";
import { NODE_TYPE_OVERRIDE_OPTIONS } from "../fleet/classify";
import {
  OP_STATUS_COLOR,
  OP_STATUS_LABEL,
  RETRYABLE_OP_STATUSES as RETRYABLE,
} from "../jobs/status";
import { FloatingWindow } from "../shell/FloatingWindow";
import { PreferredGatewaySelect } from "../shell/GatewaySelect";
import { toast } from "../shell/Toast";
import { HistoryChart, type HistoryPoint } from "./HistoryChart";
import { RemoteFlags } from "./RemoteFlags";

/**
 * El Inspector (v0.9 — "ventana de trabajo", ver plan): EL punto central de
 * interacción con un nodo, ahora como ventana flotante (`FloatingWindow`)
 * en vez de cajón fijo — movible, redimensionable, posición/tamaño
 * persistidos. Cabecera fija con identidad+vitales+acciones rápidas,
 * cuerpo organizado en pestañas (antes: acordeones apilados). Sigue siendo
 * una sola ventana global (abrir un nodo sustituye al anterior, igual que
 * antes) — el modelo de varias ventanas simultáneas queda para una fase
 * futura, `FloatingWindow` ya está diseñado para soportarlo sin reescribir.
 */

const TABS = [
  "general",
  "telemetry",
  "position",
  "gateways",
  "history",
  "operations",
  "config",
  "alerts",
  "log",
] as const;
type TabId = (typeof TABS)[number];
const TAB_LABEL: Record<TabId, string> = {
  general: "General",
  telemetry: "Telemetría",
  position: "Posición",
  gateways: "Pasarelas",
  history: "Histórico",
  operations: "Operaciones",
  config: "Configuración",
  alerts: "Alertas",
  log: "Log",
};

const iconBtn: CSSProperties = {
  background: "transparent",
  border: `1px solid ${t.border}`,
  color: t.text,
  borderRadius: 4,
  cursor: "pointer",
  fontSize: 12,
  padding: "0.1rem 0.45rem",
};

const actionBtn: CSSProperties = {
  ...iconBtn,
  fontSize: 11.5,
  padding: "0.22rem 0.6rem",
};

const inputStyle: CSSProperties = {
  background: t.bg,
  border: `1px solid ${t.border}`,
  color: t.text,
  borderRadius: 4,
  padding: "0.15rem 0.4rem",
  fontSize: 12,
  width: 110,
};

/** Celda de la rejilla de constantes vitales de la cabecera. */
function Vital({ label, value, color }: { label: string; value: ReactNode; color?: string }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ color: t.textFaint, fontSize: 9.5, letterSpacing: "0.07em" }}>{label}</div>
      <div
        style={{
          color: color ?? t.text,
          fontFamily: t.fontMono,
          fontSize: 12,
          fontVariantNumeric: "tabular-nums",
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {value}
      </div>
    </div>
  );
}

function copy(text: string, what: string) {
  navigator.clipboard?.writeText(text).then(
    () => toast(`${what} copiado`),
    () => toast(`No se pudo copiar`, { kind: "error" }),
  );
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ color: t.textFaint, fontSize: 10.5, letterSpacing: "0.06em", marginBottom: 4 }}>{label}</div>
      {children}
    </div>
  );
}

export function Inspector({
  nodeId,
  summary,
  summaries,
  operations,
  alerts,
  activity,
  onClose,
  onCenter,
  onGoTo,
  focusActive,
  onToggleFocus,
}: {
  nodeId: string;
  summary: NodeSummaryOut | undefined;
  summaries: NodeSummaryOut[];
  operations: OperationOut[];
  /** Alertas ya cargadas por App (pestaña Alertas) — filtradas aquí, sin fetch nuevo. */
  alerts: AlertOut[];
  /** Feed de actividad ya cargado por App/OpsCenter (pestaña Log) — filtrado aquí. */
  activity: ActivityEntry[];
  onClose: () => void;
  onCenter: ((lat: number, lng: number) => void) | null;
  onGoTo: (view: string) => void;
  /** Focus (§7): true si ESTE nodo es el objetivo actual. */
  focusActive: boolean;
  onToggleFocus: () => void;
}) {
  const queryClient = useQueryClient();
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["node", nodeId] });
    queryClient.invalidateQueries({ queryKey: ["nodes"] });
    queryClient.invalidateQueries({ queryKey: ["tags"] });
    queryClient.invalidateQueries({ queryKey: ["groups"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  };

  // Pestaña activa persistida (misma ventana para cualquier nodo abierto):
  // reabrir el Inspector vuelve a la última pestaña usada, no siempre a
  // "General" — coherente con recordar posición/tamaño de la ventana.
  const [tab, setTab] = usePersistedState<TabId>("window.inspector.tab", "general");

  const node = useQuery({ queryKey: ["node", nodeId], queryFn: () => fetchNode(nodeId), refetchInterval: 10_000 });
  const telemetry = useQuery({
    queryKey: ["telemetry", nodeId],
    queryFn: () => fetchNodeTelemetry(nodeId, 10),
    refetchInterval: 15_000,
  });
  const positions = useQuery({
    queryKey: ["positions", nodeId],
    queryFn: () => fetchNodePositions(nodeId, 10),
    refetchInterval: 15_000,
  });
  // Histórico: mismo endpoint append-only, más puntos, sin recalcular nada
  // — solo se pinta lo que ya persiste `node_telemetry`/`node_positions`.
  const deviceHistory = useQuery({
    queryKey: ["telemetry-history", nodeId, "device"],
    queryFn: () => fetchNodeTelemetry(nodeId, 60, "device"),
    refetchInterval: 30_000,
  });
  const envHistory = useQuery({
    queryKey: ["telemetry-history", nodeId, "environment"],
    queryFn: () => fetchNodeTelemetry(nodeId, 60, "environment"),
    refetchInterval: 30_000,
  });
  const positionHistory = useQuery({
    queryKey: ["positions-history", nodeId],
    queryFn: () => fetchNodePositions(nodeId, 30),
    refetchInterval: 30_000,
  });
  const gatewayLinks = useQuery({
    queryKey: ["node-gateways", nodeId],
    queryFn: () => fetchNodeGateways(nodeId),
    refetchInterval: 15_000,
  });
  const allTags = useQuery({ queryKey: ["tags"], queryFn: fetchTags });
  const allGroups = useQuery({ queryKey: ["groups"], queryFn: fetchGroups });
  // Mismo queryKey que App.tsx: caché compartida, sin fetch nuevo.
  const gateways = useQuery({ queryKey: ["gateways"], queryFn: () => fetchGateways() });
  // Pestaña Configuración: resumen ligero, reutiliza el mismo fetch que M1.4/M3
  // — sin reimplementar FieldControl/coerceValue del editor completo aquí.
  const configState = useQuery({
    queryKey: ["node-config", nodeId],
    queryFn: () => fetchNodeConfig(nodeId),
    enabled: tab === "config",
  });

  const favorite = useMutation({
    mutationFn: (value: boolean) => setNodeFavorite(nodeId, value),
    onSettled: invalidate,
  });
  const ignored = useMutation({
    mutationFn: (value: boolean) => setNodeIgnored(nodeId, value),
    onSettled: invalidate,
  });
  const saveTags = useMutation({
    mutationFn: (tagIds: number[]) => setNodeTags(nodeId, tagIds),
    onSettled: invalidate,
  });
  const newTag = useMutation({
    mutationFn: async (name: string) => {
      const tag = await createTag(name);
      const current = (summary?.tags ?? []).map((x) => x.id);
      await setNodeTags(nodeId, [...current, tag.id]);
    },
    onSettled: invalidate,
  });
  const membership = useMutation({
    mutationFn: ({ groupId, member }: { groupId: number; member: boolean }) =>
      member ? addGroupMember(groupId, nodeId) : removeGroupMember(groupId, nodeId),
    onSettled: invalidate,
  });
  const newGroup = useMutation({
    mutationFn: async (name: string) => {
      const group = await createGroup(name);
      await addGroupMember(group.id, nodeId);
    },
    onSettled: invalidate,
  });
  const preferredGateway = useMutation({
    mutationFn: (gatewayId: string | null) => setNodePreferredGateway(nodeId, gatewayId),
    onSettled: invalidate,
  });
  const nodeType = useMutation({
    mutationFn: (nodeType: string | null) => setNodeTypeOverride(nodeId, nodeType),
    onSettled: invalidate,
  });
  const ack = useMutation({
    mutationFn: (id: number) => ackAlert(id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });

  // Acciones rápidas: GETs a 1 clic + toast (§9). Los SETs jamás desde aquí.
  const askMetadata = useMutation({
    mutationFn: () => createOperation({ node_id: nodeId, operation_type: "metadata.get" }),
    onSuccess: (op) => {
      trackOperations([op.id]); // toast de cierre cuando termine (opTracker)
      toast(`metadata.get añadida a la cola (op #${op.id})`);
    },
    onError: (e) => toast(`No se pudo encolar: ${e.message}`, { kind: "error" }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["operations"] }),
  });
  const refreshConfig = useMutation({
    mutationFn: () => refreshNodeConfig(nodeId),
    onSuccess: (r) => {
      trackOperations(r.operation_ids);
      toast(`Lectura de configuración encolada (${r.operation_ids.length} operaciones)`);
    },
    onError: (e) => toast(`No se pudo encolar: ${e.message}`, { kind: "error" }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["operations"] }),
  });
  const doRetry = useMutation({
    mutationFn: (id: number) => retryOperation(id),
    onSuccess: () => toast("Reintento encolado"),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["operations"] }),
  });

  const [tagInput, setTagInput] = useState("");
  const [groupInput, setGroupInput] = useState("");

  const n = node.data;
  const lastTel = telemetry.data?.[0];
  const lastPos = positions.data?.[0];
  const links = gatewayLinks.data ?? [];
  const activeLinks = links.filter((l) => l.active);
  const nodeOps = operations.filter((o) => o.target_node_id === nodeId).slice(0, 5);
  const nodeAlerts = alerts.filter((a) => a.subject_type === "node" && a.subject_id === nodeId);
  const nodeActiveAlerts = nodeAlerts.filter((a) => a.status !== "resolved");
  const nodeLog = activity.filter((e) => e.nodeId === nodeId).slice(0, 60);
  const nodeTagIds = new Set((summary?.tags ?? []).map((x) => x.id));
  const nodeGroupIds = new Set(summary?.group_ids ?? []);
  const subjectOptions = summaries.filter((s) => s.node.node_id !== nodeId);

  // Grupo activo ("Grupo como contexto global"): el Inspector nunca impide
  // abrir un nodo externo — solo avisa. `summary` puede llegar undefined un
  // instante (nodo recién resuelto): sin aviso hasta tener el dato real.
  const { activeGroup } = useActiveGroup();
  const outsideActiveGroup = activeGroup != null && summary != null && !nodeGroupIds.has(activeGroup.id);

  // Series históricas: derivadas puras de lo ya cargado arriba, sin cálculo
  // ni fetch adicional. SNR/RSSI NO tienen serie histórica hoy (viven en
  // `nodes`/`node_gateway_links`, estado actual, no tablas append-only) —
  // se documenta como limitación conocida (ver docs/design de la Fase D).
  function toPoints<T extends { received_at: string | null }>(rows: T[] | undefined, pick: (r: T) => number | null): HistoryPoint[] {
    return (rows ?? [])
      .filter((r) => r.received_at != null && pick(r) != null)
      .map((r) => ({ time: r.received_at as string, value: pick(r) as number }));
  }
  const batteryHistory = toPoints(deviceHistory.data, (r) => r.battery_level);
  const voltageHistory = toPoints(deviceHistory.data, (r) => r.voltage);
  const channelUtilHistory = toPoints(deviceHistory.data, (r) => r.channel_utilization);
  const temperatureHistory = toPoints(envHistory.data, (r) => r.temperature_c);

  const battery = lastTel?.battery_level;
  const batteryText =
    battery == null ? "—" : battery > 100 ? "⚡ ext." : `${battery} %`;
  const batteryColor = battery != null && battery <= 100 && battery < 25 ? t.crit : undefined;

  const badge = (n: number, color: string = t.accent) =>
    n > 0 ? (
      <span style={{ fontFamily: t.fontMono, fontSize: 10, color, marginLeft: 4 }}>{n}</span>
    ) : null;

  // Apertura por defecto (solo antes de que exista una posición/tamaño
  // persistidos, ver `FloatingWindow`/`usePersistedState`): centrada, 80 %
  // del viewport — una vez el usuario arrastra o redimensiona, esa
  // preferencia manda en las siguientes aperturas.
  const defaultW = Math.round(window.innerWidth * 0.8);
  const defaultH = Math.round(window.innerHeight * 0.8);

  return (
    <FloatingWindow
      id="inspector"
      icon="◧"
      title={
        <>
          <span style={{ color: n?.online ? t.ok : t.textFaint, marginRight: 6 }}>●</span>
          {n?.short_name ?? nodeId}
          {n?.long_name && <span style={{ color: t.textDim, fontWeight: 400, marginLeft: 6 }}>{n.long_name}</span>}
        </>
      }
      defaultPos={{ x: Math.round((window.innerWidth - defaultW) / 2), y: Math.round((window.innerHeight - defaultH) / 2) }}
      defaultSize={{ w: defaultW, h: defaultH }}
      minWidth={380}
      minHeight={360}
      onClose={onClose}
      headerActions={
        <>
          <button
            style={{
              ...iconBtn,
              color: focusActive ? t.accent : t.textFaint,
              borderColor: focusActive ? t.accent : t.border,
              background: focusActive ? t.accentTint : "transparent",
            }}
            title={focusActive ? "Salir de Focus" : "Enfocar: el mapa, la actividad y los trabajos priorizan este nodo (nada se oculta)"}
            onClick={onToggleFocus}
          >
            ◎
          </button>
          <button
            style={{ ...iconBtn, color: n?.is_favorite ? t.warn : t.textFaint }}
            title={n?.is_favorite ? "Quitar de favoritos (local)" : "Marcar favorito (local)"}
            onClick={() => favorite.mutate(!n?.is_favorite)}
          >
            {n?.is_favorite ? "★" : "☆"}
          </button>
          <button
            style={{ ...iconBtn, color: n?.is_ignored ? t.crit : t.textFaint }}
            title={n?.is_ignored ? "Dejar de ignorar (local)" : "Ignorar (local)"}
            onClick={() => ignored.mutate(!n?.is_ignored)}
          >
            👁
          </button>
          {onCenter && lastPos && (
            <button style={iconBtn} title="Centrar en el mapa" onClick={() => onCenter(lastPos.latitude, lastPos.longitude)}>
              ⌖
            </button>
          )}
        </>
      }
    >
      {/* Cabecera fija (bajo el chrome de FloatingWindow): identidad extra + vitales + acciones rápidas */}
      <div style={{ background: t.surface, borderBottom: `1px solid ${t.border}`, padding: "0.5rem 0.75rem", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
          <span
            onClick={() => copy(nodeId, "node_id")}
            title="Copiar node_id"
            style={{ fontFamily: t.fontMono, fontSize: 11.5, color: t.textDim, cursor: "pointer" }}
          >
            {nodeId} ⧉
          </span>
          <span style={{ color: t.textFaint, fontSize: 11 }}>
            {n?.hw_model ?? "—"} · fw {n?.firmware_version ?? "—"}
            {n?.role ? ` · ${n.role}` : ""}
          </span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "0.5rem", marginTop: 8 }}>
          <Vital label="BATERÍA" value={batteryText} color={batteryColor} />
          <Vital label="SNR / RSSI" value={`${n?.snr ?? "—"} dB · ${n?.rssi ?? "—"}`} />
          <Vital label="SALTOS" value={n?.hops_away ?? "—"} />
          <Vital label="VISTO" value={relativeTime(n?.last_seen_at)} />
        </div>
        <div style={{ display: "flex", gap: 6, marginTop: 9 }}>
          <button style={actionBtn} disabled={askMetadata.isPending} onClick={() => askMetadata.mutate()} title="Encola metadata.get (solo lectura)">
            ⚙ Pedir metadata
          </button>
          <button style={actionBtn} disabled={refreshConfig.isPending} onClick={() => refreshConfig.mutate()} title="Encola la lectura de todas las secciones de configuración (solo lectura)">
            ⟳ Leer configuración
          </button>
        </div>
        {n?.is_ignored && (
          <div style={{ ...chipStyle(t.textDim), display: "inline-block", marginTop: 8, fontSize: 10.5 }}>
            nodo ignorado — fuera de agregados y alertas
          </div>
        )}
        {outsideActiveGroup && (
          <div style={{ ...chipStyle(t.warn), display: "inline-block", marginTop: 8, marginLeft: n?.is_ignored ? 6 : 0, fontSize: 10.5 }}>
            ⤫ nodo fuera del grupo activo ({activeGroup!.name})
          </div>
        )}
      </div>

      {/* Tira de pestañas */}
      <div style={{ display: "flex", overflowX: "auto", borderBottom: `1px solid ${t.border}`, background: t.surface, flexShrink: 0 }}>
        {TABS.map((id) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            style={{
              background: "transparent",
              border: "none",
              borderBottom: `2px solid ${tab === id ? t.accent : "transparent"}`,
              color: tab === id ? t.text : t.textDim,
              fontSize: 11.5,
              padding: "0.5rem 0.65rem",
              cursor: "pointer",
              whiteSpace: "nowrap",
              flexShrink: 0,
            }}
          >
            {TAB_LABEL[id]}
            {id === "operations" &&
              badge(nodeOps.filter((o) => !["succeeded", "succeeded_unconfirmed", "cancelled"].includes(o.status)).length)}
            {id === "alerts" && badge(nodeActiveAlerts.length, nodeActiveAlerts.some((a) => a.severity === "CRITICAL") ? t.crit : t.warn)}
            {id === "gateways" && badge(activeLinks.length, t.textDim)}
          </button>
        ))}
      </div>

      {/* Cuerpo: contenido de la pestaña activa */}
      <div style={{ flex: 1, overflowY: "auto", padding: "0.75rem" }}>
        {node.isError && <p style={{ color: t.crit }}>Error cargando {nodeId}</p>}

        {tab === "general" && (
          <>
            <Section label="ETIQUETAS">
              <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", alignItems: "center" }}>
                {(allTags.data ?? []).map((x) => {
                  const has = nodeTagIds.has(x.id);
                  return (
                    <button
                      key={x.id}
                      style={{ ...chipStyle(has ? t.accent : t.textFaint), cursor: "pointer", fontSize: 11 }}
                      onClick={() => {
                        const next = new Set(nodeTagIds);
                        if (has) next.delete(x.id);
                        else next.add(x.id);
                        saveTags.mutate([...next]);
                      }}
                    >
                      {x.name}
                    </button>
                  );
                })}
                <input
                  style={inputStyle}
                  placeholder="+ etiqueta"
                  value={tagInput}
                  onChange={(e) => setTagInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && tagInput.trim()) {
                      newTag.mutate(tagInput.trim());
                      setTagInput("");
                    }
                  }}
                />
              </div>
            </Section>

            <Section label="GRUPOS">
              <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", alignItems: "center" }}>
                {(allGroups.data ?? []).map((g) => {
                  const member = nodeGroupIds.has(g.id);
                  return (
                    <button
                      key={g.id}
                      style={{ ...chipStyle(member ? t.accent : t.textFaint), cursor: "pointer", fontSize: 11 }}
                      onClick={() => membership.mutate({ groupId: g.id, member: !member })}
                      title={`${g.member_count} nodos`}
                    >
                      {g.name}
                    </button>
                  );
                })}
                <input
                  style={inputStyle}
                  placeholder="+ grupo"
                  value={groupInput}
                  onChange={(e) => setGroupInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && groupInput.trim()) {
                      newGroup.mutate(groupInput.trim());
                      setGroupInput("");
                    }
                  }}
                />
              </div>
            </Section>

            <Section label="GATEWAY PREFERIDO">
              <PreferredGatewaySelect
                value={summary?.node.preferred_gateway_id ?? null}
                onChange={(gatewayId) => preferredGateway.mutate(gatewayId)}
                gateways={gateways.data ?? []}
              />
            </Section>

            <Section label="TIPO DE NODO">
              <select
                className="input"
                style={{ fontSize: 12 }}
                value={summary?.node.node_type_override ?? ""}
                title="Clasificación manual: con valor, tiene prioridad absoluta sobre la automática (Flota, bloques, estadísticas de grupo)"
                onChange={(e) => nodeType.mutate(e.target.value === "" ? null : e.target.value)}
              >
                {NODE_TYPE_OVERRIDE_OPTIONS.map((opt) => (
                  <option key={opt.id ?? "auto"} value={opt.id ?? ""}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </Section>

            <Section label="REMOTO (NODEDB DEL NODO)">
              <RemoteFlags nodeId={nodeId} subjectOptions={subjectOptions} />
            </Section>
          </>
        )}

        {tab === "telemetry" && (
          <>
            {!lastTel && <div style={{ color: t.textFaint, fontSize: 12 }}>Sin telemetría registrada.</div>}
            {lastTel && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "0.5rem" }}>
                <Vital label="VOLTAJE" value={lastTel.voltage != null ? `${lastTel.voltage} V` : "—"} />
                <Vital label="USO CANAL" value={lastTel.channel_utilization != null ? `${lastTel.channel_utilization} %` : "—"} />
                <Vital label="AIR TX" value={lastTel.air_util_tx != null ? `${lastTel.air_util_tx} %` : "—"} />
                <Vital label="UPTIME" value={lastTel.uptime_seconds != null ? `${Math.round(lastTel.uptime_seconds / 3600)} h` : "—"} />
                <Vital label="RECIBIDA" value={relativeTime(lastTel.received_at)} />
                <Vital label="VÍA" value={lastTel.gateway_id ?? "—"} />
              </div>
            )}
          </>
        )}

        {tab === "position" && (
          <>
            <Section label="ACTUAL">
              {!lastPos && (
                <div style={{ color: t.textFaint, fontSize: 12 }}>Sin posiciones registradas (sin GPS o aún sin difundir).</div>
              )}
              {lastPos && (
                <>
                  <div
                    onClick={() => copy(`${lastPos.latitude.toFixed(6)}, ${lastPos.longitude.toFixed(6)}`, "Coordenadas")}
                    title="Copiar coordenadas"
                    style={{ fontFamily: t.fontMono, fontSize: 12, cursor: "pointer" }}
                  >
                    {lastPos.latitude.toFixed(6)}, {lastPos.longitude.toFixed(6)} ⧉
                  </div>
                  <div style={{ color: t.textDim, fontSize: 11.5, fontFamily: t.fontMono, marginTop: 2 }}>
                    {lastPos.altitude_m != null ? `${lastPos.altitude_m} m` : "— m"} ·{" "}
                    {lastPos.sats_in_view != null ? `${lastPos.sats_in_view} sats` : "— sats"} ·{" "}
                    {relativeTime(lastPos.received_at)}
                  </div>
                </>
              )}
            </Section>
            <Section label="CAMBIOS DE POSICIÓN">
              {positionHistory.data == null || positionHistory.data.length === 0 ? (
                <div style={{ color: t.textFaint, fontSize: 11.5 }}>Sin posiciones registradas.</div>
              ) : (
                positionHistory.data.slice(0, 12).map((p, i) => (
                  <div key={`${p.received_at}-${i}`} style={{ fontSize: 11.5, fontFamily: t.fontMono, padding: "0.1rem 0" }}>
                    {relativeTime(p.received_at)} · {p.latitude.toFixed(4)}, {p.longitude.toFixed(4)}
                  </div>
                ))
              )}
            </Section>
          </>
        )}

        {tab === "gateways" && (
          <>
            {links.length === 0 && (
              <div style={{ color: t.textFaint, fontSize: 12 }}>Ninguna recepción directa registrada todavía.</div>
            )}
            {links.map((l) => (
              <div key={l.gateway_id} style={{ display: "flex", alignItems: "baseline", gap: "0.45rem", padding: "0.16rem 0", fontSize: 12, opacity: l.active ? 1 : 0.55 }}>
                <span style={{ color: l.active ? t.ok : t.textFaint, fontSize: 9 }}>●</span>
                <span style={{ fontFamily: t.fontMono }}>{l.gateway_id}</span>
                {l.primary && (
                  <span style={{ color: t.warn, fontSize: 11 }} title="Pasarela primaria (mejor señal activa)">
                    ◆
                  </span>
                )}
                <span style={{ color: t.textDim, fontFamily: t.fontMono, fontSize: 11, marginLeft: "auto" }}>
                  {l.snr != null ? `${l.snr} dB` : "—"} · {l.rssi != null ? `${l.rssi} dBm` : "—"} ·{" "}
                  {l.hops_away != null ? `${l.hops_away} saltos` : "—"} · {relativeTime(l.last_heard_at)}
                </span>
              </div>
            ))}
            {links.length > 0 && (
              <div style={{ color: t.textFaint, fontSize: 11, paddingTop: 4 }}>
                Enrutado admin:{" "}
                {summary?.node.preferred_gateway_id
                  ? `preferido (${summary.node.preferred_gateway_id}, ↓ General)`
                  : "automático (◆ primaria)"}
              </div>
            )}
          </>
        )}

        {tab === "history" && (
          <>
            <Section label="BATERÍA">
              <HistoryChart points={batteryHistory} unit="%" color={t.ok} />
            </Section>
            <Section label="VOLTAJE">
              <HistoryChart points={voltageHistory} unit="V" color={t.accent} />
            </Section>
            <Section label="USO DE CANAL">
              <HistoryChart points={channelUtilHistory} unit="%" color={t.warn} />
            </Section>
            <Section label="TEMPERATURA">
              <HistoryChart points={temperatureHistory} unit="°C" color={t.crit} />
            </Section>
            <Section label="SNR / RSSI">
              <div style={{ color: t.textFaint, fontSize: 11.5 }}>
                Sin serie histórica todavía — hoy solo se persiste el último valor
                (`nodes`/`node_gateway_links`), no una tabla append-only. Ver docs/design/motor-de-reglas-y-topologia.md.
              </div>
            </Section>
            <Section label="REINICIOS">
              <div style={{ color: t.textFaint, fontSize: 11.5 }}>
                Sin dato explícito de reinicio — señal indirecta pendiente
                (caída de `uptime_seconds` respecto a la lectura anterior).
              </div>
            </Section>
          </>
        )}

        {tab === "operations" && (
          <>
            {nodeOps.length === 0 && <div style={{ color: t.textFaint, fontSize: 12 }}>Sin operaciones recientes.</div>}
            {nodeOps.map((op) => (
              <div key={op.id} style={{ display: "flex", alignItems: "baseline", gap: "0.45rem", padding: "0.16rem 0", fontSize: 12 }}>
                <span style={{ color: t.textFaint, fontFamily: t.fontMono, fontSize: 11 }}>#{op.id}</span>
                <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {op.operation_type}
                  {typeof op.params.section === "string" ? `:${op.params.section}` : ""}
                </span>
                <span
                  style={{ ...chipStyle(OP_STATUS_COLOR[op.status] ?? t.textDim), fontSize: 10.5 }}
                  title={`estado técnico: ${op.status}`}
                >
                  {OP_STATUS_LABEL[op.status] ?? op.status}
                </span>
                {RETRYABLE.has(op.status) && (
                  <button style={iconBtn} title="Reintentar (re-evalúa la pasarela)" onClick={() => doRetry.mutate(op.id)}>
                    ↻
                  </button>
                )}
              </div>
            ))}
            <div style={{ paddingTop: 8 }}>
              <button style={actionBtn} onClick={() => onGoTo("jobs")}>
                Ver todas en Trabajos →
              </button>
            </div>
          </>
        )}

        {tab === "config" && (
          <>
            {configState.isLoading && <div style={{ color: t.textFaint, fontSize: 12 }}>Cargando…</div>}
            {configState.data && (
              <>
                {configState.data.sections.length === 0 && (
                  <div style={{ color: t.textFaint, fontSize: 12 }}>
                    Sin secciones leídas todavía — usa «Leer configuración» arriba.
                  </div>
                )}
                {configState.data.sections.map((s) => (
                  <div key={s.section} style={{ display: "flex", alignItems: "baseline", gap: "0.45rem", padding: "0.16rem 0", fontSize: 12 }}>
                    <span style={{ fontFamily: t.fontMono }}>{s.section}</span>
                    <span style={{ color: t.textFaint, fontSize: 11 }}>{s.kind}</span>
                    <span style={{ color: t.textDim, fontFamily: t.fontMono, fontSize: 11, marginLeft: "auto" }}>
                      {relativeTime(s.last_read_at)}
                    </span>
                  </div>
                ))}
              </>
            )}
            <div style={{ paddingTop: 10 }}>
              <button style={{ ...actionBtn, width: "100%" }} onClick={() => onGoTo("config")}>
                ✎ Abrir editor completo →
              </button>
            </div>
          </>
        )}

        {tab === "alerts" && (
          <>
            {nodeAlerts.length === 0 && <div style={{ color: t.textFaint, fontSize: 12 }}>Sin alertas para este nodo.</div>}
            {nodeAlerts.map((a) => {
              const color = alertSeverityColor(a.severity);
              return (
                <div key={a.id} style={{ display: "flex", alignItems: "flex-start", gap: "0.45rem", padding: "0.22rem 0", fontSize: 12, borderBottom: `1px solid ${t.borderSubtle}` }}>
                  <span style={{ color, fontSize: 10, lineHeight: "18px" }}>●</span>
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ color: t.text }}>{a.message}</span>{" "}
                    <span style={{ color: t.textFaint, fontSize: 11 }}>
                      {relativeTime(a.fired_at)}
                      {a.status === "acknowledged" && " · ACK"}
                      {a.status === "resolved" && " · resuelta"}
                    </span>
                  </span>
                  {a.status === "firing" && (
                    <button style={iconBtn} title="Reconocer la alerta" disabled={ack.isPending} onClick={() => ack.mutate(a.id)}>
                      ACK
                    </button>
                  )}
                </div>
              );
            })}
          </>
        )}

        {tab === "log" && (
          <>
            {nodeLog.length === 0 && <div style={{ color: t.textFaint, fontSize: 12 }}>Sin eventos registrados para este nodo.</div>}
            {nodeLog.map((e) => (
              <div key={e.id} style={{ fontSize: 11.5, fontFamily: t.fontMono, padding: "0.18rem 0", borderBottom: `1px solid ${t.borderSubtle}` }}>
                <span style={{ color: t.textFaint }}>{relativeTime(e.time)}</span>{" "}
                <span style={{ color: t.text, fontFamily: t.fontUi }}>{e.text}</span>
              </div>
            ))}
          </>
        )}
      </div>
    </FloatingWindow>
  );
}

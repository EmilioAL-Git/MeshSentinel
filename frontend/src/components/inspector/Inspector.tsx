import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { usePersistedState } from "../../hooks/usePersistedState";
import {
  ackAlert,
  addGroupMember,
  createGroup,
  createOperation,
  createTag,
  fetchDashboardSummary,
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
import { relativeTime } from "../../time";
import { alertSeverityColor, chipStyle, t } from "../../tokens";
import { trackOperations } from "../../opTracker";
import { useActiveGroup } from "../../context/GroupContext";
import { CATEGORY_DEFS, NODE_TYPE_OVERRIDE_OPTIONS, classifyNode } from "../fleet/classify";
import { Signal } from "../fleet/instruments";
import {
  OP_STATUS_COLOR,
  OP_STATUS_LABEL,
  RETRYABLE_OP_STATUSES as RETRYABLE,
  TERMINAL_OP_STATUSES,
  fmtSeconds,
  opTypeLabel,
} from "../jobs/status";
import { FloatingWindow } from "../shell/FloatingWindow";
import { PreferredGatewaySelect } from "../shell/GatewaySelect";
import { toast } from "../shell/Toast";
import { HistoryChart, type HistoryPoint } from "./HistoryChart";
import { NodeLog } from "./NodeLog";
import { RemoteFlags } from "./RemoteFlags";

/**
 * El Inspector: panel de control de UN nodo (rediseño "3 segundos" — el
 * operador debe leer estado/tráfico/ubicación/observadores/problemas/
 * actividad reciente sin cambiar de pestaña). Cabecera+KPIs fijos arriba,
 * pestañas debajo para el detalle. Sigue siendo una `FloatingWindow` única
 * (mismas reglas de posición/tamaño persistidos). Reorganización pura: cero
 * queries nuevas, cero datos nuevos — todo reutiliza lo que ya se cargaba.
 */

const TABS = [
  "log",
  "telemetry",
  "position",
  "gateways",
  "config",
  "operations",
  "alerts",
  "history",
  "general",
] as const;
type TabId = (typeof TABS)[number];
const TAB_LABEL: Record<TabId, string> = {
  log: "Actividad",
  telemetry: "Telemetría",
  position: "Posición",
  gateways: "Pasarelas",
  config: "Configuración",
  operations: "Operaciones",
  alerts: "Alertas",
  history: "Histórico",
  general: "Organización",
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

const microlabel: CSSProperties = {
  color: t.textFaint,
  fontSize: 9.5,
  fontWeight: 650,
  letterSpacing: "0.07em",
  textTransform: "uppercase",
};

/** Celda de la rejilla de constantes vitales de la cabecera. */
function Vital({ label, value, color }: { label: string; value: ReactNode; color?: string }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={microlabel}>{label}</div>
      <div
        style={{
          color: color ?? t.text,
          fontFamily: t.fontMono,
          fontSize: 14,
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

/** Tarjeta de métrica (Telemetría/Posición): icono + valor grande + etiqueta — nunca una fila de tabla. */
function MetricCard({
  icon,
  label,
  value,
  color,
  onClick,
  title,
}: {
  icon: string;
  label: string;
  value: ReactNode;
  color?: string;
  onClick?: () => void;
  title?: string;
}) {
  return (
    <div
      onClick={onClick}
      title={title}
      style={{
        background: t.surface2,
        border: `1px solid ${t.borderSubtle}`,
        borderRadius: 6,
        padding: "0.5rem 0.65rem",
        minWidth: 0,
        cursor: onClick ? "pointer" : undefined,
      }}
    >
      <div style={{ fontSize: 14, opacity: 0.85 }}>{icon}</div>
      <div
        style={{
          fontFamily: t.fontMono,
          fontSize: 17,
          color: color ?? t.text,
          fontVariantNumeric: "tabular-nums",
          marginTop: 2,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {value}
      </div>
      <div style={{ ...microlabel, marginTop: 2 }}>{label}</div>
    </div>
  );
}

const cardGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(110px, 1fr))",
  gap: "0.5rem",
};

function copy(text: string, what: string) {
  navigator.clipboard?.writeText(text).then(
    () => toast(`${what} copiado`),
    () => toast(`No se pudo copiar`, { kind: "error" }),
  );
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ ...microlabel, marginBottom: 4 }}>{label}</div>
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
  // "Actividad" — coherente con recordar posición/tamaño de la ventana.
  const [tab, setTab] = usePersistedState<TabId>("window.inspector.tab", "log");

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
  // También sirve de fuente para las tarjetas de la pestaña Telemetría
  // (kind explícito → más fiable que la mezcla sin filtrar de arriba).
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
  // Umbrales de la red (hardening): el color de batería usa
  // thresholds.low_battery_percent, nunca un valor hardcodeado. Mismo
  // queryKey que App.tsx — caché compartida.
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: fetchDashboardSummary });
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
  const deviceLatest = deviceHistory.data?.[0];
  const envLatest = envHistory.data?.[0];
  const lastPos = positions.data?.[0];
  const links = gatewayLinks.data ?? [];
  const activeLinks = links.filter((l) => l.active);
  const allNodeOps = operations.filter((o) => o.target_node_id === nodeId);
  const nodeOps = allNodeOps.slice(0, 8);
  const pendingOps = allNodeOps.filter((o) => !TERMINAL_OP_STATUSES.has(o.status));
  const nodeAlerts = alerts.filter((a) => a.subject_type === "node" && a.subject_id === nodeId);
  const nodeActiveAlerts = nodeAlerts.filter((a) => a.status !== "resolved");
  const nodeTagIds = new Set((summary?.tags ?? []).map((x) => x.id));
  const nodeGroupIds = new Set(summary?.group_ids ?? []);
  const groupNames = [...nodeGroupIds]
    .map((id) => allGroups.data?.find((g) => g.id === id)?.name)
    .filter((name): name is string => name != null);
  const subjectOptions = summaries.filter((s) => s.node.node_id !== nodeId);

  // Clasificación (Flota): misma función única del resto de la app —
  // gatewayNodeIds se deriva de `gateways` (ya cargado), sin fetch nuevo.
  const gatewayNodeIds = useMemo(
    () => new Set((gateways.data ?? []).map((g) => g.local_node_id).filter((x): x is string => x != null)),
    [gateways.data],
  );
  const category = summary ? classifyNode(summary, gatewayNodeIds) : null;
  const categoryDef = category ? CATEGORY_DEFS.find((c) => c.id === category) : undefined;

  const primaryLink = links.find((l) => l.primary) ?? null;
  const primaryGatewayId = primaryLink?.gateway_id ?? n?.gateway_id ?? null;
  const primaryGatewayName =
    (primaryGatewayId && gateways.data?.find((g) => g.gateway_id === primaryGatewayId)?.name) || primaryGatewayId;

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
  const batteryText = battery == null ? "—" : battery > 100 ? "⚡ ext." : `${battery} %`;
  const lowBatteryThreshold = dashboard.data?.thresholds.low_battery_percent ?? 20;
  const batteryColor = battery != null && battery <= 100 && battery < lowBatteryThreshold ? t.crit : undefined;
  const uptimeText = deviceLatest?.uptime_seconds != null ? fmtSeconds(deviceLatest.uptime_seconds) : "—";

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
      minWidth={420}
      minHeight={420}
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
            onClick={() => {
              // El tooltip nativo (hover) apenas se descubre — al activar
              // Focus, explicarlo también por toast (pedido del usuario).
              if (!focusActive) {
                toast(
                  `Focus activado en ${n?.short_name ?? nodeId}: el mapa lo resalta (y atenúa el resto salvo alertas), ` +
                    "la Actividad y los Trabajos lo priorizan arriba — nada se oculta. Pulsa ◎ otra vez para salir.",
                );
              }
              onToggleFocus();
            }}
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
      {/* Cabecera: identidad + vitales grandes de un vistazo (≈20-25% de la ventana) */}
      <div style={{ background: t.surface, borderBottom: `1px solid ${t.border}`, padding: "0.65rem 0.85rem", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: "0.7rem" }}>
          <div
            title={categoryDef?.label ?? "Sin clasificar"}
            style={{
              width: 42,
              height: 42,
              flexShrink: 0,
              borderRadius: 8,
              background: t.surface2,
              border: `1px solid ${t.border}`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 19,
            }}
          >
            {categoryDef?.icon ?? "❓"}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
              <span style={{ color: n?.online ? t.ok : t.textFaint, fontSize: 10 }}>{n?.online ? "●" : "○"}</span>
              <span style={{ fontSize: 18, fontWeight: 700, color: t.text }}>{n?.short_name ?? nodeId}</span>
              {n?.long_name && <span style={{ fontSize: 12.5, color: t.textDim, fontWeight: 400 }}>{n.long_name}</span>}
              <span
                onClick={() => copy(nodeId, "node_id")}
                title="Copiar node_id"
                style={{ fontFamily: t.fontMono, fontSize: 11, color: t.textFaint, cursor: "pointer" }}
              >
                {nodeId} ⧉
              </span>
            </div>
            <div style={{ color: t.textFaint, fontSize: 11, marginTop: 2 }}>
              {categoryDef?.label ?? "Sin clasificar"} · {n?.hw_model ?? "—"} · fw {n?.firmware_version ?? "—"}
              {n?.role ? ` · ${n.role}` : ""}
            </div>
            {(groupNames.length > 0 || (summary?.tags?.length ?? 0) > 0) && (
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 6 }}>
                {groupNames.map((name) => (
                  <span key={name} className="chip" style={{ borderColor: t.accent, color: t.accent }}>
                    {name}
                  </span>
                ))}
                {(summary?.tags ?? []).map((tg) => (
                  <span key={tg.id} className="chip" style={{ borderColor: tg.color ?? t.border, color: tg.color ?? t.textDim }}>
                    {tg.name}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(96px, 1fr))", gap: "0.55rem", marginTop: 10 }}>
          <div>
            <div style={microlabel}>BATERÍA</div>
            {battery == null ? (
              <div style={{ fontFamily: t.fontMono, fontSize: 18, color: t.textFaint }}>—</div>
            ) : battery > 100 ? (
              <div style={{ fontFamily: t.fontMono, fontSize: 18, color: t.ok }}>⚡ ext.</div>
            ) : (
              <div style={{ display: "flex", alignItems: "baseline", gap: 7 }}>
                <span style={{ fontFamily: t.fontMono, fontSize: 18, color: batteryColor ?? t.text }}>{battery}%</span>
                <span className="track" style={{ width: 60 }}>
                  <span className="fill" style={{ width: `${battery}%`, background: batteryColor ?? t.ok }} />
                </span>
              </div>
            )}
          </div>
          <Vital label="SNR / RSSI" value={`${n?.snr ?? "—"} dB · ${n?.rssi ?? "—"} dBm`} />
          <Vital label="SALTOS" value={n?.hops_away ?? "—"} />
          <Vital label="VISTO" value={relativeTime(n?.last_seen_at)} />
          <Vital label="PASARELA" value={primaryGatewayName ?? "—"} />
        </div>

        <div style={{ display: "flex", gap: 6, marginTop: 9, flexWrap: "wrap" }}>
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

      {/* Fila de KPIs: valores grandes, cero tablas */}
      <div className="kpis">
        <div className="kpi">
          <div className="v" style={{ color: batteryColor ?? t.text }}>
            {batteryText}
          </div>
          <div className="k">🔋 Batería</div>
        </div>
        <div className="kpi">
          <div className="v">{uptimeText}</div>
          <div className="k">⏱ Uptime</div>
        </div>
        <div className="kpi">
          <div className="v">{activeLinks.length}</div>
          <div className="k">🛰 Pasarelas</div>
        </div>
        <div className="kpi">
          <div className="v" style={{ color: nodeActiveAlerts.some((a) => a.severity === "CRITICAL") ? t.crit : nodeActiveAlerts.length > 0 ? t.warn : t.text }}>
            {nodeActiveAlerts.length}
          </div>
          <div className="k">⚠ Alertas</div>
        </div>
        <div className="kpi">
          <div className="v" style={{ color: pendingOps.length > 0 ? t.accent : t.text }}>{pendingOps.length}</div>
          <div className="k">⚙ Operaciones</div>
        </div>
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
            {id === "operations" && badge(pendingOps.length)}
            {id === "alerts" && badge(nodeActiveAlerts.length, nodeActiveAlerts.some((a) => a.severity === "CRITICAL") ? t.crit : t.warn)}
            {id === "gateways" && badge(activeLinks.length, t.textDim)}
          </button>
        ))}
      </div>

      {/* Cuerpo: contenido de la pestaña activa */}
      <div style={{ flex: 1, overflowY: "auto", padding: "0.75rem" }}>
        {node.isError && <p style={{ color: t.crit }}>Error cargando {nodeId}</p>}

        {tab === "log" && <NodeLog nodeId={nodeId} />}

        {tab === "telemetry" && (
          <>
            {!deviceLatest && !envLatest && <div className="empty">Sin telemetría registrada.</div>}
            {(deviceLatest || envLatest) && (
              <div style={cardGrid}>
                {deviceLatest?.battery_level != null && (
                  <MetricCard
                    icon="🔋"
                    label="BATERÍA"
                    color={deviceLatest.battery_level <= 100 && deviceLatest.battery_level < lowBatteryThreshold ? t.crit : undefined}
                    value={deviceLatest.battery_level > 100 ? "⚡ ext." : `${deviceLatest.battery_level} %`}
                  />
                )}
                {deviceLatest?.uptime_seconds != null && (
                  <MetricCard icon="⏱" label="UPTIME" value={fmtSeconds(deviceLatest.uptime_seconds)} />
                )}
                {deviceLatest?.voltage != null && <MetricCard icon="🔌" label="VOLTAJE" value={`${deviceLatest.voltage} V`} />}
                {deviceLatest?.channel_utilization != null && (
                  <MetricCard icon="📶" label="USO CANAL" value={`${deviceLatest.channel_utilization} %`} />
                )}
                {deviceLatest?.air_util_tx != null && <MetricCard icon="📡" label="AIR TX" value={`${deviceLatest.air_util_tx} %`} />}
                {envLatest?.temperature_c != null && <MetricCard icon="🌡" label="TEMPERATURA" value={`${envLatest.temperature_c} °C`} />}
                {envLatest?.relative_humidity != null && (
                  <MetricCard icon="💧" label="HUMEDAD" value={`${envLatest.relative_humidity} %`} />
                )}
                {envLatest?.barometric_pressure_hpa != null && (
                  <MetricCard icon="🧭" label="PRESIÓN" value={`${envLatest.barometric_pressure_hpa} hPa`} />
                )}
              </div>
            )}
            {(deviceLatest || envLatest) && (
              <div style={{ marginTop: 10, fontSize: 11, color: t.textFaint }}>
                Última recepción: {relativeTime(deviceLatest?.received_at ?? envLatest?.received_at ?? null)} · vía{" "}
                {deviceLatest?.gateway_id ?? envLatest?.gateway_id ?? "—"}
              </div>
            )}
          </>
        )}

        {tab === "position" && (
          <>
            {!lastPos && <div className="empty">Sin posiciones registradas (sin GPS o aún sin difundir).</div>}
            {lastPos && (
              <>
                <div style={cardGrid}>
                  <MetricCard
                    icon="📍"
                    label="COORDENADAS"
                    value={`${lastPos.latitude.toFixed(5)}, ${lastPos.longitude.toFixed(5)}`}
                    title="Copiar coordenadas"
                    onClick={() => copy(`${lastPos.latitude.toFixed(6)}, ${lastPos.longitude.toFixed(6)}`, "Coordenadas")}
                  />
                  <MetricCard icon="⛰" label="ALTITUD" value={lastPos.altitude_m != null ? `${lastPos.altitude_m} m` : "—"} />
                  <MetricCard icon="🛰" label="SATÉLITES" value={lastPos.sats_in_view ?? "—"} />
                  <MetricCard icon="🕒" label="ACTUALIZADA" value={relativeTime(lastPos.received_at)} />
                </div>
                {onCenter && (
                  <button className="btn" style={{ marginTop: 10 }} onClick={() => onCenter(lastPos.latitude, lastPos.longitude)}>
                    ⌖ Centrar en el mapa principal
                  </button>
                )}
              </>
            )}
            <div style={{ marginTop: 14 }}>
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
            </div>
          </>
        )}

        {tab === "gateways" && (
          <>
            {links.length === 0 && <div className="empty">Ninguna recepción directa registrada todavía.</div>}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {links.map((l) => {
                const gw = gateways.data?.find((g) => g.gateway_id === l.gateway_id);
                return (
                  <div
                    key={l.gateway_id}
                    style={{
                      border: `1px solid ${t.borderSubtle}`,
                      borderLeft: `3px solid ${l.active ? (l.primary ? t.warn : t.ok) : t.textFaint}`,
                      borderRadius: 6,
                      padding: "0.45rem 0.65rem",
                      opacity: l.active ? 1 : 0.55,
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                      <strong style={{ fontSize: 12.5 }}>{gw?.name || l.gateway_id}</strong>
                      {l.primary && (
                        <span style={{ ...chipStyle(t.warn), fontSize: 10 }} title="Pasarela primaria (mejor señal activa)">
                          ◆ primaria
                        </span>
                      )}
                      <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 4 }}>
                        <Signal snr={l.snr} />
                      </span>
                    </div>
                    <div style={{ fontFamily: t.fontMono, fontSize: 11, color: t.textDim, marginTop: 3 }}>
                      {l.snr != null ? `${l.snr} dB` : "—"} · {l.rssi != null ? `${l.rssi} dBm` : "—"} ·{" "}
                      {l.hops_away != null ? `${l.hops_away} saltos` : "—"} · {relativeTime(l.last_heard_at)}
                    </div>
                  </div>
                );
              })}
            </div>
            {links.length > 0 && (
              <div style={{ color: t.textFaint, fontSize: 11, paddingTop: 8 }}>
                Enrutado admin:{" "}
                {summary?.node.preferred_gateway_id
                  ? `preferido (${summary.node.preferred_gateway_id}, ↓ General)`
                  : "automático (◆ primaria)"}
              </div>
            )}
          </>
        )}

        {tab === "config" && (
          <>
            {configState.isLoading && <div style={{ color: t.textFaint, fontSize: 12 }}>Cargando…</div>}
            {configState.data && (
              <>
                {configState.data.sections.length === 0 && (
                  <div className="empty">Sin secciones leídas todavía — usa «Leer configuración» arriba.</div>
                )}
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {configState.data.sections.map((s) => (
                    <div
                      key={s.section}
                      style={{
                        display: "flex",
                        alignItems: "baseline",
                        gap: "0.45rem",
                        padding: "0.3rem 0.55rem",
                        fontSize: 12,
                        background: t.surface2,
                        border: `1px solid ${t.borderSubtle}`,
                        borderRadius: 5,
                      }}
                    >
                      <span style={{ fontFamily: t.fontMono }}>{s.section}</span>
                      <span style={{ color: t.textFaint, fontSize: 11 }}>{s.kind}</span>
                      <span style={{ color: t.textDim, fontFamily: t.fontMono, fontSize: 11, marginLeft: "auto" }}>
                        {relativeTime(s.last_read_at)}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}
            <div style={{ paddingTop: 10 }}>
              <button style={{ ...actionBtn, width: "100%" }} onClick={() => onGoTo("config")}>
                ✎ Abrir editor completo →
              </button>
            </div>
          </>
        )}

        {tab === "operations" && (
          <>
            {nodeOps.length === 0 && <div className="empty">Sin operaciones recientes.</div>}
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {nodeOps.map((op) => (
                <div
                  key={op.id}
                  style={{
                    padding: "0.35rem 0.55rem",
                    fontSize: 12,
                    background: t.surface2,
                    border: `1px solid ${t.borderSubtle}`,
                    borderRadius: 5,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "baseline", gap: "0.45rem" }}>
                    <span style={{ color: t.textFaint, fontFamily: t.fontMono, fontSize: 11 }}>#{op.id}</span>
                    <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {opTypeLabel(op.operation_type, op.params)}
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
                  <div style={{ color: t.textFaint, fontSize: 10.5, marginTop: 3 }}>
                    por {op.actor_label} · vía {op.gateway_id} · {fmtSeconds(op.duration_ms != null ? op.duration_ms / 1000 : null)}
                  </div>
                </div>
              ))}
            </div>
            <div style={{ paddingTop: 8 }}>
              <button style={actionBtn} onClick={() => onGoTo("jobs")}>
                Ver todas en Trabajos →
              </button>
            </div>
          </>
        )}

        {tab === "alerts" && (
          <>
            {nodeAlerts.length === 0 && <div className="empty">Sin alertas para este nodo.</div>}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {nodeAlerts.map((a) => {
                const color = alertSeverityColor(a.severity);
                return (
                  <div
                    key={a.id}
                    style={{
                      border: `1px solid ${t.borderSubtle}`,
                      borderLeft: `3px solid ${color}`,
                      borderRadius: 6,
                      padding: "0.4rem 0.6rem",
                      fontSize: 12,
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "flex-start", gap: "0.5rem" }}>
                      <span style={{ flex: 1, minWidth: 0, color: t.text }}>{a.message}</span>
                      {a.status === "firing" && (
                        <button style={iconBtn} title="Reconocer la alerta" disabled={ack.isPending} onClick={() => ack.mutate(a.id)}>
                          ACK
                        </button>
                      )}
                    </div>
                    <div style={{ color: t.textFaint, fontSize: 11, marginTop: 3 }}>
                      {relativeTime(a.fired_at)}
                      {a.status === "acknowledged" && " · reconocida"}
                      {a.status === "resolved" && " · resuelta"}
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}

        {tab === "history" && (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "0.6rem 1rem" }}>
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
            </div>
            <div style={{ color: t.textFaint, fontSize: 11, marginTop: 6 }}>
              SNR/RSSI y reinicios no tienen serie histórica hoy — solo se persiste el último valor
              (ver docs/design/motor-de-reglas-y-topologia.md).
            </div>
          </>
        )}

        {tab === "general" && (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "0 1rem" }}>
              <div>
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
              </div>

              <div>
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
              </div>
            </div>

            <Section label="REMOTO (NODEDB DEL NODO)">
              <RemoteFlags nodeId={nodeId} subjectOptions={subjectOptions} />
            </Section>
          </>
        )}
      </div>
    </FloatingWindow>
  );
}

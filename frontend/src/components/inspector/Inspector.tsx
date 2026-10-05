import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useAuth } from "../../context/AuthContext";
import { LockedNotice } from "../shell/LockedNotice";
import { useUrlString } from "../../hooks/useUrlState";
import {
  ackAlert,
  addGroupMember,
  createGroup,
  createOperation,
  ensureMyGroup,
  createTag,
  deleteNode,
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
  displayName,
  setNodeIgnored,
  setNodePreferredGateway,
  setNodeTags,
  setNodeTypeOverride,
  type AlertOut,
  type NodeSummaryOut,
  type OperationOut,
} from "../../api/client";
import { relativeTime } from "../../time";
import { alertSeverityColor, chipStyle, hex, t } from "../../tokens";
import { trackOperations } from "../../opTracker";
import { useActiveGroup } from "../../context/GroupContext";
import { CATEGORY_DEFS, NODE_TYPE_OVERRIDE_OPTIONS, classifyNode } from "../fleet/classify";
import { Signal } from "../fleet/instruments";
import { IgnoreNodeModal } from "../fleet/IgnoreNodeModal";
import { NexusCatIcon } from "../nexus/NexusCatIcon";
import { NodeNexusPanel } from "../nexus/NodeNexusPanel";
import { useNexusMode } from "../nexus/useNexusMode";
import {
  FAILED_OP_STATUSES,
  OP_STATUS_COLOR,
  OP_STATUS_LABEL,
  RETRYABLE_OP_STATUSES as RETRYABLE,
  TERMINAL_OP_STATUSES,
  fmtSeconds,
  fmtUptime,
  opTypeLabel,
} from "../jobs/status";
import { displayValue } from "../ConfigEditor";
import { ConfirmModal } from "../shell/ConfirmModal";
import { FloatingWindow } from "../shell/FloatingWindow";
import { PreferredGatewaySelect } from "../shell/GatewaySelect";
import { toast } from "../shell/Toast";
import type { HistoryPoint } from "./HistoryChart";

// ECharts pesa ~1 MB: chunk aparte, solo se descarga al abrir la pestaña Histórico
const HistoryChart = lazy(() => import("./HistoryChart").then((m) => ({ default: m.HistoryChart })));
import { NodeLog } from "./NodeLog";
import { computeNodeStats24h, TRAFFIC_LEVEL_LABEL } from "./nodeStats24h";
import { PositionMiniMap } from "./PositionMiniMap";
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
  "resumen",
  "log",
  "telemetry",
  "position",
  "gateways",
  "config",
  "operations",
  "nexus",
  "alerts",
  "history",
  "general",
] as const;
type TabId = (typeof TABS)[number];
const LOCKED_TABS: ReadonlySet<TabId> = new Set<TabId>(["operations", "nexus", "general"]);
const TAB_LABEL: Record<TabId, string> = {
  resumen: "Resumen",
  log: "Actividad",
  telemetry: "Telemetría",
  position: "Posición",
  gateways: "Pasarelas",
  config: "Configuración",
  operations: "Operaciones",
  nexus: "JenTastic-Nexus",
  alerts: "Alertas",
  history: "Estadísticas",
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

const RADIO_REQUESTS = [
  { kind: "user_info", label: "Info de usuario", hint: "Nombre, hardware y clave del nodo." },
  { kind: "position", label: "Posición", hint: "Última posición del nodo." },
  { kind: "device_metrics", label: "Métricas del dispositivo", hint: "Batería, uso de canal, aire TX, uptime." },
  { kind: "environment_metrics", label: "Métricas de entorno", hint: "Temperatura, humedad, presión." },
  { kind: "air_quality_metrics", label: "Calidad del aire", hint: "Partículas PM y CO₂." },
  { kind: "power_metrics", label: "Métricas de energía", hint: "Tensión y corriente por canal." },
  { kind: "local_stats", label: "Estadísticas locales", hint: "Paquetes, ruido y colisiones del nodo." },
  { kind: "host_metrics", label: "Métricas del host", hint: "Memoria y carga (nodos Linux)." },
  { kind: "pax_metrics", label: "Contador de personas", hint: "Dispositivos WiFi/BLE cercanos (paxcounter)." },
] as const;

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
  onDeleted,
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
  /** Borrado real del nodo (distinto de is_ignored): App limpia selección/caché. */
  onDeleted: () => void;
}) {
  const queryClient = useQueryClient();
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["node", nodeId] });
    queryClient.invalidateQueries({ queryKey: ["nodes"] });
    queryClient.invalidateQueries({ queryKey: ["tags"] });
    queryClient.invalidateQueries({ queryKey: ["groups"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  };

  // Pestaña activa: preferencia persistida (misma ventana para cualquier
  // nodo abierto — reabrir el Inspector vuelve a la última pestaña usada)
  // por defecto, pero URLs compartibles (ADR 0026) dejan que un enlace con
  // `tab=` la sobrescriba — "cómo tengo montado el puesto" (localStorage)
  // cede ante "qué le estoy enseñando a alguien" (URL) cuando esta última
  // está presente.
  // Abrir un nodo SIEMPRE arranca en «Resumen», salvo que la URL traiga un
  // `tab=` (enlace compartido en la primera carga). Al cambiar de nodo o
  // cerrar el Inspector se limpia `tab` para que no sobreviva al siguiente.
  const [urlTab, setUrlTab] = useUrlString("tab", null, { replace: true });
  const tab: TabId = urlTab != null && (TABS as readonly string[]).includes(urlTab) ? (urlTab as TabId) : "resumen";
  const setTab = useCallback((next: TabId) => setUrlTab(next), [setUrlTab]);
  const prevNodeId = useRef(nodeId);
  useEffect(() => {
    if (prevNodeId.current !== nodeId) {
      prevNodeId.current = nodeId;
      setUrlTab(null);
    }
  }, [nodeId, setUrlTab]);
  useEffect(() => () => setUrlTab(null), [setUrlTab]);

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
  // Resumen 24h: ventana propia (limit alto, no los 60/30 puntos de los
  // gráficos de arriba, pensados para "tendencia visible" no "cobertura
  // completa de la ventana") — se calcula en cliente, mismo criterio que
  // groupStats.ts/highlights.ts, nada nuevo en el backend.
  const deviceStats24h = useQuery({
    queryKey: ["telemetry-24h", nodeId, "device"],
    queryFn: () => fetchNodeTelemetry(nodeId, 500, "device"),
    refetchInterval: 60_000,
  });
  const envStats24h = useQuery({
    queryKey: ["telemetry-24h", nodeId, "environment"],
    queryFn: () => fetchNodeTelemetry(nodeId, 500, "environment"),
    refetchInterval: 60_000,
  });
  const positionStats24h = useQuery({
    queryKey: ["positions-24h", nodeId],
    queryFn: () => fetchNodePositions(nodeId, 500),
    refetchInterval: 60_000,
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
  // Grupo del usuario (ADR 0029): alta/baja del nodo en el grupo personal de
  // la cuenta; lo crea bajo demanda. Disponible para cualquier rol con sesión.
  const myGroup = (allGroups.data ?? []).find((g) => g.is_personal);
  const inMyGroup = myGroup != null && (summary?.group_ids ?? []).includes(myGroup.id);
  const toggleMyGroup = useMutation({
    mutationFn: async () => {
      const g = myGroup ?? (await ensureMyGroup());
      if (inMyGroup) await removeGroupMember(g.id, nodeId);
      else await addGroupMember(g.id, nodeId);
    },
    onSettled: () => {
      invalidate();
      queryClient.invalidateQueries({ queryKey: ["groups"] });
    },
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
  // Borrado real e irreversible (distinto de is_ignored, que solo lo oculta):
  // fila del nodo + su historial propio. Botón armado en 2 pasos (sin
  // teclear nada, pedido explícito del usuario), mismo patrón que
  // GatewaysView/DeleteNodeModal.
  const [deleteArmed, setDeleteArmed] = useState(false);
  // Ignorar pide confirmación (reversible, pero oculta el nodo); dejar de ignorar va directo.
  const [confirmIgnore, setConfirmIgnore] = useState(false);
  const [confirmRefreshConfig, setConfirmRefreshConfig] = useState(false);
  const deleteThisNode = useMutation({
    mutationFn: () => deleteNode(nodeId),
    onSuccess: () => {
      invalidate();
      onDeleted();
    },
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
    onError: (e) => toast(`No se pudo añadir a la cola: ${e.message}`, { kind: "error" }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["operations"] }),
  });
  const runTraceroute = useMutation({
    mutationFn: () => createOperation({ node_id: nodeId, operation_type: "traceroute.run" }),
    onSuccess: (op) => {
      trackOperations([op.id]);
      toast(`Traceroute añadido a la cola (op #${op.id})`);
    },
    onError: (e) => toast(`No se pudo añadir a la cola: ${e.message}`, { kind: "error" }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["operations"] }),
  });
  const radioRequest = useMutation({
    mutationFn: (r: { kind: string; label: string }) =>
      createOperation({ node_id: nodeId, operation_type: "request.send", params: { kind: r.kind } }),
    onSuccess: (op, r) => {
      trackOperations([op.id]);
      toast(`Solicitud «${r.label}» enviada a la cola (op #${op.id})`);
    },
    onError: (e) => toast(`No se pudo añadir a la cola: ${e.message}`, { kind: "error" }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["operations"] }),
  });
  const refreshConfig = useMutation({
    mutationFn: () => refreshNodeConfig(nodeId),
    onSuccess: (r) => {
      trackOperations(r.operation_ids);
      toast(`Lectura de configuración añadida a la cola (${r.operation_ids.length} operaciones)`);
    },
    onError: (e) => toast(`No se pudo añadir a la cola: ${e.message}`, { kind: "error" }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["operations"] }),
  });
  const doRetry = useMutation({
    mutationFn: (id: number) => retryOperation(id),
    onSuccess: () => toast("Reintento añadido a la cola"),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["operations"] }),
  });

  const [tagInput, setTagInput] = useState("");
  const [groupInput, setGroupInput] = useState("");

  const n = node.data;
  const nexusModeOn = useNexusMode();
  // Punto 7 del encargo (ADR 0027 §4/§7): pestaña "JenTastic-Nexus" separada
  // de "Operaciones" (pipeline nativo AdminMessage/PKC, ADR 0013) — solo
  // visible con el flag global ON y este nodo marcado, nunca uno sin el
  // otro (mismo criterio que la insignia del gato). Si el nodo deja de
  // cumplir esa condición mientras la pestaña estaba activa (se desmarca,
  // se apaga el flag) cae a "Actividad" en vez de quedarse en una pestaña
  // fantasma.
  const showNexusTab = nexusModeOn && (n?.is_nexus ?? false);
  const visibleTabs = showNexusTab ? TABS : TABS.filter((id) => id !== "nexus");
  // Pestañas que escriben (organización, operaciones, Nexus): visibles pero
  // bloqueadas sin sesión — el backend las rechaza igualmente con 401.
  const { canOperate, hasPersonalSpace } = useAuth();
  const effectiveTab: TabId = (visibleTabs as readonly TabId[]).includes(tab) ? tab : "resumen";
  const locked = !canOperate && LOCKED_TABS.has(effectiveTab);
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
  const airTxHistory = toPoints(deviceHistory.data, (r) => r.air_util_tx);
  const temperatureHistory = toPoints(envHistory.data, (r) => r.temperature_c);
  const stats24h = useMemo(
    () => computeNodeStats24h(deviceStats24h.data ?? [], envStats24h.data ?? [], positionStats24h.data ?? []),
    [deviceStats24h.data, envStats24h.data, positionStats24h.data],
  );

  const battery = lastTel?.battery_level;
  const batteryText = battery == null ? "—" : battery > 100 ? "⚡ ext." : `${battery} %`;
  const lowBatteryThreshold = dashboard.data?.thresholds.low_battery_percent ?? 20;
  const batteryColor = battery != null && battery <= 100 && battery < lowBatteryThreshold ? t.crit : undefined;
  const uptimeText = deviceLatest?.uptime_seconds != null ? fmtUptime(deviceLatest.uptime_seconds) : "—";

  // Resumen (pestaña por defecto, pedida explícitamente por el usuario):
  // síntesis de "¿algo va mal?" derivada de datos YA cargados arriba, cero
  // fetches nuevos — cada problema detectado es clicable y salta a su
  // pestaña de detalle (mismo patrón que la cola de atención de StatusPanel,
  // pero a escala de un único nodo).
  const failedOps = allNodeOps.filter((o) => FAILED_OP_STATUSES.has(o.status));
  type Problem = { icon: string; label: string; color: string; tab: TabId };
  const problems: Problem[] = [];
  if (n && !n.online) problems.push({ icon: "📴", label: "Nodo offline", color: t.crit, tab: "log" });
  if (batteryColor) problems.push({ icon: "🔋", label: `Batería baja (${battery}%)`, color: t.crit, tab: "telemetry" });
  if (activeLinks.length === 0) problems.push({ icon: "🛰", label: "Sin pasarela activa", color: t.warn, tab: "gateways" });
  if (nodeActiveAlerts.length > 0) {
    const hasCritical = nodeActiveAlerts.some((a) => a.severity === "CRITICAL");
    problems.push({
      icon: "⚠",
      label: `${nodeActiveAlerts.length} alerta${nodeActiveAlerts.length > 1 ? "s" : ""} activa${nodeActiveAlerts.length > 1 ? "s" : ""}`,
      color: hasCritical ? t.crit : t.warn,
      tab: "alerts",
    });
  }
  if (failedOps.length > 0) {
    problems.push({
      icon: "⚙",
      label: `${failedOps.length} operación${failedOps.length > 1 ? "es" : ""} fallida${failedOps.length > 1 ? "s" : ""}`,
      color: t.crit,
      tab: "operations",
    });
  }
  if (stats24h.reboots > 0) {
    problems.push({
      icon: "🔁",
      label: `${stats24h.reboots} reinicio${stats24h.reboots > 1 ? "s" : ""} en 24 h`,
      color: t.warn,
      tab: "history",
    });
  }
  if (n?.is_ignored) problems.push({ icon: "👁", label: "Nodo ignorado (local)", color: t.textDim, tab: "general" });

  const badge = (n: number, color: string = t.accent) =>
    n > 0 ? (
      <span style={{ fontFamily: t.fontMono, fontSize: 10, color, marginLeft: 4 }}>{n}</span>
    ) : null;

  // Apertura por defecto (solo antes de que exista una posición/tamaño
  // persistidos, ver `FloatingWindow`/`usePersistedState`): 92 % del
  // viewport (antes 80 % — pedido del usuario: "más grande para que quepa
  // casi toda la información, pero sin ocupar toda la pantalla"), una vez
  // el usuario arrastra o redimensiona, esa preferencia manda en las
  // siguientes aperturas.
  const defaultW = Math.round(window.innerWidth * 0.92);
  const defaultH = Math.round(window.innerHeight * 0.92);

  return (
    <FloatingWindow
      id="inspector"
      icon="◧"
      title={
        <>
          <span style={{ color: n?.online ? t.ok : t.textFaint, marginRight: 6 }}>●</span>
          {nexusModeOn && n?.is_nexus && (
            <span style={{ marginRight: 5 }}>
              <NexusCatIcon size={16} />
            </span>
          )}
          {n?.short_name ?? nodeId}
          {n?.long_name && <span style={{ color: t.textDim, fontWeight: 400, marginLeft: 6 }}>{n.long_name}</span>}
        </>
      }
      defaultPos={{ x: Math.round((window.innerWidth - defaultW) / 2), y: Math.round((window.innerHeight - defaultH) / 2) }}
      defaultSize={{ w: defaultW, h: defaultH }}
      minWidth={720}
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
            title={n?.is_favorite ? "Quitar de mis favoritos" : "Añadir a mis favoritos"}
            onClick={() => favorite.mutate(!n?.is_favorite)}
          >
            {n?.is_favorite ? "★" : "☆"}
          </button>
          {hasPersonalSpace && (
            <button
              style={{ ...iconBtn, color: inMyGroup ? t.accent : t.textFaint }}
              title={inMyGroup ? "Quitar de mi Grupo del usuario" : "Añadir a mi Grupo del usuario"}
              onClick={() => toggleMyGroup.mutate()}
              disabled={toggleMyGroup.isPending}
            >
              {inMyGroup ? "◆" : "◇"}
            </button>
          )}
          {canOperate && (
          <button
            style={{ ...iconBtn, color: n?.is_ignored ? t.crit : t.textFaint }}
            title={n?.is_ignored ? "Dejar de ignorar (local)" : "Ignorar (local)"}
            onClick={() => (n?.is_ignored ? ignored.mutate(false) : setConfirmIgnore(true))}
          >
            👁
          </button>
          )}
          {confirmIgnore && (
            <IgnoreNodeModal
              nodeLabel={n ? displayName(n) : nodeId}
              onClose={() => setConfirmIgnore(false)}
              onConfirm={() => {
                ignored.mutate(true);
                setConfirmIgnore(false);
              }}
            />
          )}
          {onCenter && lastPos && (
            <button style={iconBtn} title="Centrar en el mapa" onClick={() => onCenter(lastPos.latitude, lastPos.longitude)}>
              ⌖
            </button>
          )}
        </>
      }
    >
      {/* Cuerpo en dos columnas: caja grande de pestañas+comandos a la
          izquierda, panel de detalles/info fijo a la derecha (pedido
          explícito del usuario — antes todo apilado verticalmente). */}
      <div className="insp-body" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "row" }}>
        {/* Columna izquierda: pestañas + contenido (comandos) */}
        <div className="insp-main" style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", borderRight: `1px solid ${t.border}` }}>
          {/* Tira de pestañas: botones claros en varias líneas si no caben
              en una sola (antes una fila con scroll horizontal, difícil de
              descubrir — pedido explícito del usuario). */}
          <div
            className="insp-tabs"
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 6,
              borderBottom: `1px solid ${t.border}`,
              background: t.surface,
              padding: "0.5rem 0.6rem",
              flexShrink: 0,
            }}
          >
            {visibleTabs.map((id) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                style={{
                  background: effectiveTab === id ? t.accentTint : t.surface2,
                  border: `1px solid ${effectiveTab === id ? t.accent : t.borderSubtle}`,
                  color: effectiveTab === id ? t.text : t.textDim,
                  fontSize: 12,
                  fontWeight: effectiveTab === id ? 650 : 500,
                  borderRadius: 5,
                  padding: "0.4rem 0.75rem",
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                }}
              >
                {!canOperate && LOCKED_TABS.has(id) ? "🔒 " : ""}{TAB_LABEL[id]}
                {id === "operations" && badge(pendingOps.length)}
                {id === "alerts" && badge(nodeActiveAlerts.length, nodeActiveAlerts.some((a) => a.severity === "CRITICAL") ? t.crit : t.warn)}
                {id === "gateways" && badge(activeLinks.length, t.textDim)}
              </button>
            ))}
          </div>

          {/* Cuerpo: contenido de la pestaña activa */}
          <div className="insp-content" style={{ flex: 1, overflowY: "auto", padding: "0.75rem" }}>
            {node.isError && <p style={{ color: t.crit }}>Error cargando {nodeId}</p>}

        {locked && <LockedNotice what={`La pestaña «${TAB_LABEL[effectiveTab]}»`} />}

        {effectiveTab === "resumen" && (
          <>
            <Section label="ESTADO">
              {problems.length === 0 ? (
                <div
                  style={{
                    ...chipStyle(t.ok),
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    fontSize: 12.5,
                    padding: "0.35rem 0.7rem",
                  }}
                >
                  ✓ Todo normal — sin problemas detectados
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {problems.map((p, i) => (
                    <button
                      key={i}
                      onClick={() => setTab(p.tab)}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        textAlign: "left",
                        background: t.surface2,
                        border: `1px solid ${t.borderSubtle}`,
                        borderLeft: `3px solid ${p.color}`,
                        borderRadius: 6,
                        padding: "0.45rem 0.65rem",
                        color: t.text,
                        fontSize: 12.5,
                        cursor: "pointer",
                        width: "100%",
                      }}
                    >
                      <span>{p.icon}</span>
                      <span style={{ flex: 1, minWidth: 0 }}>{p.label}</span>
                      <span style={{ color: t.textFaint, fontSize: 11 }}>ver →</span>
                    </button>
                  ))}
                </div>
              )}
            </Section>

            <Section label="DATOS RÁPIDOS">
              <div style={cardGrid}>
                <MetricCard icon="⏱" label="UPTIME" value={uptimeText} onClick={() => setTab("telemetry")} />
                <MetricCard icon="🔋" label="BATERÍA" value={batteryText} color={batteryColor} onClick={() => setTab("telemetry")} />
                {stats24h.trafficLevel != null && (
                  <MetricCard
                    icon={stats24h.trafficLevel === "alto" ? "🔴" : stats24h.trafficLevel === "moderado" ? "🟡" : "🟢"}
                    label="TRÁFICO 24H"
                    value={TRAFFIC_LEVEL_LABEL[stats24h.trafficLevel]}
                    onClick={() => setTab("history")}
                  />
                )}
                <MetricCard
                  icon="🛰"
                  label="PASARELAS ACTIVAS"
                  value={activeLinks.length}
                  color={activeLinks.length === 0 ? t.warn : undefined}
                  onClick={() => setTab("gateways")}
                />
                <MetricCard
                  icon="📍"
                  label="ÚLTIMA POSICIÓN"
                  value={lastPos ? relativeTime(lastPos.received_at) : "—"}
                  onClick={() => setTab("position")}
                />
                <MetricCard
                  icon="📨"
                  label="MUESTRAS 24H"
                  value={stats24h.deviceSamples + stats24h.envSamples + stats24h.positionSamples}
                  onClick={() => setTab("history")}
                />
              </div>
            </Section>

            <Section label="OPERACIONES">
              {allNodeOps.length === 0 ? (
                <div style={{ color: t.textFaint, fontSize: 11.5 }}>Sin operaciones registradas.</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {allNodeOps.slice(0, 3).map((op) => (
                    <div key={op.id} style={{ display: "flex", alignItems: "baseline", gap: "0.45rem", fontSize: 12 }}>
                      <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {opTypeLabel(op.operation_type, op.params)}
                      </span>
                      <span style={{ ...chipStyle(OP_STATUS_COLOR[op.status] ?? t.textDim), fontSize: 10 }}>
                        {OP_STATUS_LABEL[op.status] ?? op.status}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              <button style={{ ...actionBtn, marginTop: 8 }} onClick={() => setTab("operations")}>
                Ver todas →
              </button>
            </Section>

            <Section label="ALERTAS ACTIVAS">
              {nodeActiveAlerts.length === 0 ? (
                <div style={{ color: t.textFaint, fontSize: 11.5 }}>Sin alertas activas.</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {nodeActiveAlerts.slice(0, 3).map((a) => (
                    <div key={a.id} style={{ display: "flex", alignItems: "baseline", gap: 6, fontSize: 12, color: t.text }}>
                      <span style={{ color: alertSeverityColor(a.severity) }}>●</span>
                      <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {a.message}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              <button style={{ ...actionBtn, marginTop: 8 }} onClick={() => setTab("alerts")}>
                Ver todas →
              </button>
            </Section>
          </>
        )}

        {effectiveTab === "log" && <NodeLog nodeId={nodeId} />}

        {effectiveTab === "telemetry" && (
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
                  <MetricCard icon="⏱" label="UPTIME" value={fmtUptime(deviceLatest.uptime_seconds)} />
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

        {effectiveTab === "position" && (
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
            {positionHistory.data != null && positionHistory.data.length > 0 && (
              <div style={{ marginTop: 14 }}>
                <Section label="MAPA DEL HISTORIAL">
                  <PositionMiniMap positions={positionHistory.data} />
                </Section>
              </div>
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

        {effectiveTab === "gateways" && (
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

        {effectiveTab === "config" && (
          <>
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: t.textFaint, fontSize: 10.5, letterSpacing: 0.6, marginBottom: 4 }}>
                SOLICITAR POR RADIO · sin administración
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 5 }}>
                {RADIO_REQUESTS.map((r) => (
                  <button
                    key={r.kind}
                    style={actionBtn}
                    disabled={radioRequest.isPending}
                    title={`${r.hint} Transmite un paquete; el nodo contesta con su dato y se registra solo.`}
                    onClick={() => radioRequest.mutate(r)}
                  >
                    {r.label}
                  </button>
                ))}
                <button style={actionBtn} disabled={runTraceroute.isPending} onClick={() => runTraceroute.mutate()} title="Ruta y SNR por salto, ida y vuelta.">
                  Traceroute
                </button>
                <button style={actionBtn} disabled={askMetadata.isPending} onClick={() => askMetadata.mutate()} title="Firmware, hardware y capacidades (usa administración).">
                  Metadata
                </button>
              </div>
              <div style={{ color: t.textFaint, fontSize: 10.5, marginTop: 4 }}>
                La calidad de señal (SNR/RSSI) no se solicita: se mide en cada paquete recibido. La configuración completa solo existe por administración (botón «Leer configuración»).
              </div>
            </div>
            {configState.isLoading && <div style={{ color: t.textFaint, fontSize: 12 }}>Cargando…</div>}
            {configState.data && (
              <>
                {configState.data.sections.length === 0 && (
                  <div className="empty">Sin secciones leídas todavía — usa «Leer configuración» arriba.</div>
                )}
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {configState.data.sections.map((s) => {
                    const fields = Object.entries(s.values);
                    return (
                      <div
                        key={s.section}
                        style={{
                          padding: "0.3rem 0.55rem",
                          fontSize: 12,
                          background: t.surface2,
                          border: `1px solid ${t.borderSubtle}`,
                          borderRadius: 5,
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "baseline", gap: "0.45rem" }}>
                          <span style={{ fontFamily: t.fontMono }}>{s.section}</span>
                          <span style={{ color: t.textFaint, fontSize: 11 }}>{s.kind}</span>
                          <span style={{ color: t.textDim, fontFamily: t.fontMono, fontSize: 11, marginLeft: "auto" }}>
                            {relativeTime(s.last_read_at)}
                          </span>
                        </div>
                        {fields.length === 0 && (
                          <div style={{ color: t.textFaint, fontSize: 11, marginTop: 3 }}>Sin campos.</div>
                        )}
                        {fields.length > 0 && (
                          <div
                            style={{
                              display: "grid",
                              gridTemplateColumns: "auto 1fr",
                              columnGap: "0.5rem",
                              rowGap: 2,
                              marginTop: 5,
                              paddingTop: 5,
                              borderTop: `1px solid ${t.borderSubtle}`,
                            }}
                          >
                            {fields.map(([k, v]) => (
                              <Fragment key={k}>
                                <span style={{ color: t.textFaint, fontFamily: t.fontMono, fontSize: 11 }}>{k}</span>
                                <span style={{ fontFamily: t.fontMono, fontSize: 11, wordBreak: "break-all" }}>
                                  {displayValue(v)}
                                </span>
                              </Fragment>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </>
            )}
            <div style={{ paddingTop: 10 }}>
              <button
                style={{ ...actionBtn, width: "100%" }}
                onClick={() => {
                  onGoTo("config");
                  onClose();
                }}
              >
                ✎ Abrir editor completo →
              </button>
            </div>
          </>
        )}

        {effectiveTab === "operations" && !locked && (
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
              <button
                style={actionBtn}
                onClick={() => {
                  onGoTo("jobs");
                  onClose();
                }}
              >
                Ver todas en Trabajos →
              </button>
            </div>
          </>
        )}

        {effectiveTab === "nexus" && !locked && n?.short_name && (
          <NodeNexusPanel nodeId={nodeId} shortName={n.short_name} defaultGatewayId={primaryGatewayId} />
        )}

        {effectiveTab === "alerts" && (
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
                      {a.status === "firing" && canOperate && (
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

        {effectiveTab === "history" && (
          <>
            <Section label="RESUMEN 24 H">
              {stats24h.deviceSamples === 0 && stats24h.envSamples === 0 && stats24h.positionSamples === 0 ? (
                <div style={{ color: t.textFaint, fontSize: 11.5 }}>Sin muestras en las últimas 24 h.</div>
              ) : (
                <>
                  {stats24h.trafficLevel != null && (
                    <div style={{ marginBottom: 8 }}>
                      <span
                        style={{
                          ...chipStyle(
                            stats24h.trafficLevel === "alto"
                              ? t.crit
                              : stats24h.trafficLevel === "moderado"
                                ? t.warn
                                : t.ok,
                          ),
                          fontSize: 11.5,
                          padding: "0.2rem 0.6rem",
                        }}
                        title="Clasificado por el air_util_tx medio de la ventana (>30 % alto, >10 % moderado, resto bajo)"
                      >
                        {stats24h.trafficLevel === "alto" ? "🔴" : stats24h.trafficLevel === "moderado" ? "🟡" : "🟢"}{" "}
                        {TRAFFIC_LEVEL_LABEL[stats24h.trafficLevel]} · TX medio {stats24h.avgAirUtilTx} %
                      </span>
                    </div>
                  )}
                  <div style={cardGrid}>
                    {stats24h.currentUptimeSeconds != null && (
                      <MetricCard icon="⏱" label="UPTIME ACTUAL" value={fmtUptime(stats24h.currentUptimeSeconds)} />
                    )}
                    <MetricCard
                      icon="🔁"
                      label="REINICIOS 24H"
                      value={stats24h.reboots}
                      color={stats24h.reboots > 0 ? t.warn : undefined}
                    />
                    {stats24h.avgAirUtilTx != null && (
                      <MetricCard icon="📡" label="AIR TX MEDIO" value={`${stats24h.avgAirUtilTx} %`} />
                    )}
                    {stats24h.maxAirUtilTx != null && (
                      <MetricCard icon="📡" label="AIR TX PICO" value={`${stats24h.maxAirUtilTx} %`} />
                    )}
                    {stats24h.avgChannelUtil != null && (
                      <MetricCard icon="📶" label="CANAL MEDIO" value={`${stats24h.avgChannelUtil} %`} />
                    )}
                    {stats24h.maxChannelUtil != null && (
                      <MetricCard icon="📶" label="CANAL PICO" value={`${stats24h.maxChannelUtil} %`} />
                    )}
                    {stats24h.minBattery != null && stats24h.maxBattery != null && (
                      <MetricCard icon="🔋" label="BATERÍA MIN/MAX" value={`${stats24h.minBattery}–${stats24h.maxBattery} %`} />
                    )}
                    {stats24h.batteryDeltaPercent != null && (
                      <MetricCard
                        icon={stats24h.batteryDeltaPercent >= 0 ? "🔌" : "🪫"}
                        label="CAMBIO BATERÍA"
                        value={`${stats24h.batteryDeltaPercent > 0 ? "+" : ""}${stats24h.batteryDeltaPercent} %`}
                        color={stats24h.batteryDeltaPercent < 0 ? t.warn : t.ok}
                      />
                    )}
                    {stats24h.minTemperatureC != null && stats24h.maxTemperatureC != null && (
                      <MetricCard icon="🌡" label="TEMP. MIN/MAX" value={`${stats24h.minTemperatureC}–${stats24h.maxTemperatureC} °C`} />
                    )}
                    {stats24h.minHumidity != null && stats24h.maxHumidity != null && (
                      <MetricCard icon="💧" label="HUMEDAD MIN/MAX" value={`${stats24h.minHumidity}–${stats24h.maxHumidity} %`} />
                    )}
                    {stats24h.minPressureHpa != null && stats24h.maxPressureHpa != null && (
                      <MetricCard icon="🧭" label="PRESIÓN MIN/MAX" value={`${stats24h.minPressureHpa}–${stats24h.maxPressureHpa} hPa`} />
                    )}
                    {stats24h.distanceKm != null && (
                      <MetricCard icon="🧭" label="DISTANCIA RECORRIDA" value={`${stats24h.distanceKm} km`} />
                    )}
                    {stats24h.maxSpeedKmh != null && (
                      <MetricCard icon="🚀" label="VELOCIDAD MÁXIMA" value={`${stats24h.maxSpeedKmh} km/h`} />
                    )}
                    <MetricCard
                      icon="📨"
                      label="MUESTRAS 24H"
                      value={stats24h.deviceSamples + stats24h.envSamples + stats24h.positionSamples}
                      title="Telemetría de dispositivo + entorno + posiciones recibidas en la ventana"
                    />
                  </div>
                  <div style={{ color: t.textFaint, fontSize: 11, marginTop: 6 }}>
                    Distancia/velocidad son aproximadas (ruido de GPS incluido, no un dato de precisión). Reinicios
                    se infieren de caídas en `uptime_seconds`, mismo criterio que la narrativa del diario operativo.
                  </div>
                </>
              )}
            </Section>

            <Suspense fallback={<div className="empty">Cargando gráficas…</div>}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "0.6rem 1rem" }}>
              <Section label="BATERÍA">
                <HistoryChart points={batteryHistory} unit="%" color={hex.catGreen} />
              </Section>
              <Section label="VOLTAJE">
                <HistoryChart points={voltageHistory} unit="V" color={hex.catBlue} />
              </Section>
              <Section label="USO DE CANAL">
                <HistoryChart points={channelUtilHistory} unit="%" color={hex.catViolet} />
              </Section>
              <Section label="USO TX (AIR TIME)">
                <HistoryChart points={airTxHistory} unit="%" color={hex.catAqua} />
              </Section>
              <Section label="TEMPERATURA">
                <HistoryChart points={temperatureHistory} unit="°C" color={hex.catOrange} />
              </Section>
            </div>
            </Suspense>
            <div style={{ color: t.textFaint, fontSize: 11, marginTop: 6 }}>
              SNR/RSSI no tienen serie histórica hoy — solo se persiste el último valor
              (ver docs/design/motor-de-reglas-y-topologia.md).
            </div>
          </>
        )}

        {effectiveTab === "general" && !locked && (
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
              <RemoteFlags nodeId={nodeId} subjectOptions={subjectOptions} nexusActive={showNexusTab} />
            </Section>

            <Section label="PELIGRO">
              <p style={{ fontSize: 12, color: t.textDim, marginTop: 0 }}>
                Se elimina la información del nodo y todo su historial propio (posiciones,
                telemetría, vecinos, etiquetas, grupos, enlaces con pasarelas). Es{" "}
                <strong>irreversible</strong>. No es como "ignorar", que solo lo oculta.
                <br />
                Los registros de Actividad/Alertas/Operaciones que lo incluyen no se borran.
              </p>
              {deleteArmed ? (
                <button
                  style={{ ...actionBtn, borderColor: t.crit, color: t.crit }}
                  disabled={deleteThisNode.isPending}
                  onClick={() => deleteThisNode.mutate()}
                >
                  ¿Seguro? Confirmar borrado
                </button>
              ) : (
                <button
                  style={{ ...actionBtn, borderColor: t.crit, color: t.crit }}
                  onClick={() => setDeleteArmed(true)}
                >
                  Borrar nodo
                </button>
              )}
              {deleteThisNode.isError && (
                <p style={{ color: t.crit, fontSize: 12 }}>{String(deleteThisNode.error)}</p>
              )}
            </Section>
          </>
        )}
          </div>
        </div>

        {/* Columna derecha: detalles / info del nodo, fija */}
        <div
          className="insp-info"
          style={{
            width: 340,
            flexShrink: 0,
            overflowY: "auto",
            background: t.surface,
            padding: "0.75rem 0.9rem",
          }}
        >
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
                <span style={{ fontSize: 16, fontWeight: 700, color: t.text }}>{n?.short_name ?? nodeId}</span>
              </div>
              {n?.long_name && <div style={{ fontSize: 12.5, color: t.textDim, fontWeight: 400, marginTop: 2 }}>{n.long_name}</div>}
              <div
                onClick={() => copy(nodeId, "node_id")}
                title="Copiar node_id"
                style={{ fontFamily: t.fontMono, fontSize: 11, color: t.textFaint, cursor: "pointer", marginTop: 2 }}
              >
                {nodeId} ⧉
              </div>
              <div style={{ color: t.textFaint, fontSize: 11, marginTop: 4 }}>
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

          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "0.7rem 0.6rem", marginTop: 14 }}>
            <div style={{ minWidth: 0 }}>
              <div style={microlabel}>BATERÍA</div>
              {battery == null ? (
                <div style={{ fontFamily: t.fontMono, fontSize: 16, color: t.textFaint }}>—</div>
              ) : battery > 100 ? (
                <div style={{ fontFamily: t.fontMono, fontSize: 16, color: t.ok }}>⚡ ext.</div>
              ) : (
                <div style={{ display: "flex", alignItems: "baseline", gap: 7 }}>
                  <span style={{ fontFamily: t.fontMono, fontSize: 16, color: batteryColor ?? t.text }}>{battery}%</span>
                  <span className="track" style={{ width: 44 }}>
                    <span className="fill" style={{ width: `${battery}%`, background: batteryColor ?? t.ok }} />
                  </span>
                </div>
              )}
            </div>
            <Vital label="SALTOS" value={n?.hops_away ?? "—"} />
            <Vital label="SNR / RSSI" value={`${n?.snr ?? "—"} dB · ${n?.rssi ?? "—"} dBm`} />
            <Vital label="VISTO" value={relativeTime(n?.last_seen_at)} />
            <Vital label="PASARELA" value={primaryGatewayName ?? "—"} />
          </div>

          <div className="insp-actions" style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 12 }}>
            <button style={{ ...actionBtn, width: "100%" }} disabled={askMetadata.isPending} onClick={() => askMetadata.mutate()} title="Añade metadata.get a la cola (solo lectura)">
              ⚙ Pedir metadata
            </button>
            <button
              style={{ ...actionBtn, width: "100%" }}
              disabled={runTraceroute.isPending}
              onClick={() => runTraceroute.mutate()}
              title="Envía un traceroute real por radio (hasta 5 saltos): muestra ruta y SNR por salto. Transmite un paquete por la malla."
            >
              ⌁ Traceroute
            </button>
            <button
              style={{ ...actionBtn, width: "100%" }}
              disabled={refreshConfig.isPending}
              onClick={() => setConfirmRefreshConfig(true)}
              title="Añade a la cola la lectura de todas las secciones de configuración (solo lectura)"
            >
              ⟳ Leer configuración
            </button>
            {confirmRefreshConfig && (
              <ConfirmModal
                title="Leer configuración completa"
                message="Esto añade 26 lecturas a la cola (una por cada sección de configuración más el propietario). Es solo lectura, pero ocupa tiempo de aire de la malla mientras se completan."
                confirmLabel="Leer las 26 secciones"
                onConfirm={() => {
                  setConfirmRefreshConfig(false);
                  refreshConfig.mutate();
                }}
                onCancel={() => setConfirmRefreshConfig(false)}
              />
            )}
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

          {/* KPIs: valores grandes, cero tablas. La clase `.kpis` es
              `display:flex` (pensada para una fila ancha) — en esta
              columna estrecha 5 ítems en fila cortaban el texto; se
              fuerza grid de 2 columnas aquí. */}
          <div className="kpis insp-kpis" style={{ marginTop: 12, display: "grid", gridTemplateColumns: "1fr 1fr" }}>
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
        </div>
      </div>
    </FloatingWindow>
  );
}

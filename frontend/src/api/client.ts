export interface ComponentStatus {
  status: "ok" | "error";
  detail: string | null;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  database: ComponentStatus;
  redis: ComponentStatus;
}

export interface NodeOut {
  node_id: string;
  node_num: number | null;
  short_name: string | null;
  long_name: string | null;
  hw_model: string | null;
  firmware_version: string | null;
  role: string | null;
  snr: number | null;
  rssi: number | null;
  hops_away: number | null;
  via_mqtt: boolean;
  gateway_id: string | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  is_favorite: boolean;
  is_ignored: boolean;
  is_nexus: boolean;
  preferred_gateway_id: string | null;
  node_type_override: string | null;
  online: boolean;
}

/** "NOMBRE (!id)" o solo el id si el nodo no tiene nombre. */
export function displayName(node: {
  node_id: string;
  short_name: string | null;
  long_name: string | null;
}): string {
  const name = node.long_name || node.short_name;
  return name ? `${name} (${node.node_id})` : node.node_id;
}

export interface PositionOut {
  node_id: string;
  latitude: number;
  longitude: number;
  altitude_m: number | null;
  precision_bits: number | null;
  sats_in_view: number | null;
  position_time: string | null;
  received_at: string | null;
  gateway_id: string | null;
}

export interface TelemetryOut {
  node_id: string;
  kind: "device" | "environment" | "power";
  battery_level: number | null;
  voltage: number | null;
  channel_utilization: number | null;
  air_util_tx: number | null;
  uptime_seconds: number | null;
  temperature_c: number | null;
  relative_humidity: number | null;
  barometric_pressure_hpa: number | null;
  received_at: string | null;
  gateway_id: string | null;
}

export interface TagOut {
  id: number;
  name: string;
  color: string | null;
}

export interface GroupOut {
  id: number;
  name: string;
  kind: string;
  is_critical: boolean;
  member_count: number;
  preferred_gateway_id: string | null;
  /** Grupo del usuario (ADR 0029): privado, uno por cuenta, nunca predeterminado. */
  is_personal: boolean;
}

/** Observación de un nodo por una pasarela concreta (node_gateway_links, M6.1/M6.2). */
export interface NodeGatewayLinkOut {
  node_id: string;
  gateway_id: string;
  rssi: number | null;
  snr: number | null;
  hops_away: number | null;
  via_mqtt: boolean;
  first_heard_at: string | null;
  last_heard_at: string | null;
  active: boolean;
  primary: boolean;
}

export interface NodeSummaryOut {
  node: NodeOut;
  last_position: PositionOut | null;
  last_device_telemetry: TelemetryOut | null;
  tags: TagOut[];
  group_ids: number[];
  gateway_links: NodeGatewayLinkOut[];
}

/** Enlace nodo<->nodo real (NEIGHBORINFO_APP), topología de malla. */
export interface NeighborOut {
  node_id: string;
  neighbor_id: string;
  snr: number | null;
  received_at: string | null;
  gateway_id: string | null;
  active: boolean;
}

/** Nº de pasarelas que oyen al nodo ahora mismo (enlaces activos). */
export function activeGatewayCount(s: NodeSummaryOut): number {
  return s.gateway_links.filter((l) => l.active).length;
}

export interface NodeFilterParams {
  q?: string;
  hw_model?: string;
  tag?: string;
  group_id?: number;
  favorite?: boolean;
  online?: boolean;
  battery_below?: number;
  gateway_id?: string;
  include_ignored?: boolean;
  only_ignored?: boolean;
  nexus?: boolean;
}

export type GatewayStatus = "unassigned" | "connecting" | "reconnecting" | "connected" | "disconnected" | "error";

export interface GatewayOut {
  gateway_id: string;
  status: GatewayStatus | string;
  transport: string;
  local_node_id: string | null;
  detail: string | null;
  updated_at: string | null;
  local_short_name: string | null;
  local_long_name: string | null;
  local_hw_model: string | null;
  local_firmware_version: string | null;
  // Tres señales independientes: nodo responde (viva) / RX LoRa / TX LoRa
  last_device_response_at: string | null;
  last_lora_rx_at: string | null;
  last_lora_tx_at: string | null;
  name: string | null;
  managed: boolean;
  transport_type: string | null;
  connection_params: Record<string, unknown>;
  enabled: boolean;
  priority: number;
  desired_status: "connected" | "disconnected";
  container_managed: boolean;
  deleted_at: string | null;
  last_connected_at: string | null;
  last_disconnected_at: string | null;
  last_error: string | null;
  last_error_at: string | null;
}

// ── Interceptor global de 401 (autenticación) ───────────────────────────────
// Un único punto para las ~40 mutaciones de este cliente: no se toca ningún
// call site. Al recibir 401 se avisa a quien esté escuchando (AuthContext
// abre el modal de login) y el error sigue propagándose normalmente — la
// mutación en curso falla igual que antes (toast/estado de error), el
// operador reintenta la acción tras iniciar sesión.
type UnauthorizedListener = () => void;
let unauthorizedListener: UnauthorizedListener | null = null;
export function onUnauthorized(listener: UnauthorizedListener | null): void {
  unauthorizedListener = listener;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api/v1${path}`);
  if (res.status === 401) unauthorizedListener?.();
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${path}`);
  return res.json();
}

export const fetchHealth = () => get<HealthResponse>("/health");

export function fetchNodes(filters: NodeFilterParams = {}): Promise<NodeSummaryOut[]> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return get<NodeSummaryOut[]>(`/nodes${qs ? `?${qs}` : ""}`);
}
export const fetchNode = (id: string) => get<NodeOut>(`/nodes/${encodeURIComponent(id)}`);
export const fetchNodePositions = (id: string, limit = 50) =>
  get<PositionOut[]>(`/nodes/${encodeURIComponent(id)}/positions?limit=${limit}`);
export const fetchNodeTelemetry = (id: string, limit = 50, kind?: "device" | "environment" | "power") =>
  get<TelemetryOut[]>(
    `/nodes/${encodeURIComponent(id)}/telemetry?limit=${limit}${kind ? `&kind=${kind}` : ""}`,
  );
export const fetchNodeGateways = (id: string) =>
  get<NodeGatewayLinkOut[]>(`/nodes/${encodeURIComponent(id)}/gateways`);
/** Vecindario actual del nodo: último enlace por vecino, sin duplicados. */
export const fetchNodeNeighbors = (id: string) =>
  get<NeighborOut[]>(`/nodes/${encodeURIComponent(id)}/neighbors`);
/** Topología: último enlace nodo<->nodo por par, oído en las últimas `sinceHours` (24 por defecto). */
export const fetchTopology = (sinceHours?: number) =>
  get<NeighborOut[]>(`/topology${sinceHours ? `?since_hours=${sinceHours}` : ""}`);
export const fetchGateways = (includeDeleted = false) =>
  get<GatewayOut[]>(`/gateways${includeDeleted ? "?include_deleted=true" : ""}`);

// ── Estadísticas Multi-Gateway (M6.2) ────────────────────────────────────────

export interface GatewayStatsOut {
  gateway_id: string;
  name: string | null;
  status: string;
  nodes_visible: number;
  nodes_exclusive: number;
  nodes_shared: number;
  primary_for: number;
  last_heard_at: string | null;
}

export interface MultiGatewayStatsOut {
  generated_at: string;
  nodes_observed: number;
  nodes_shared: number;
  redundancy_percent: number;
  gateways: GatewayStatsOut[];
}

export const fetchGatewayStats = (groupId?: number) =>
  get<MultiGatewayStatsOut>(`/gateways/stats${groupId != null ? `?group_id=${groupId}` : ""}`);

// ── Gestión de gateways (M5) ─────────────────────────────────────────────────

export interface DeviceOut {
  port: string;
  description: string | null;
  vid: string | null;
  pid: string | null;
  serial_number: string | null;
}

export interface TestConnectionResultOut {
  ok: boolean;
  error: string | null;
  local_node_id: string | null;
  local_short_name: string | null;
  local_long_name: string | null;
  local_hw_model: string | null;
  local_firmware_version: string | null;
}

/** Dispositivos USB del host vía gateway-launcher (ADR 0028) — para "Crear
 * un contenedor nuevo", antes de que exista ningún proceso al que
 * correlacionar. Distinto de discoverDevices(), que pregunta a un proceso
 * YA vivo. */
export const fetchLauncherDevices = () => get<DeviceOut[]>("/gateways/devices");

export interface CreateGatewayIn {
  gateway_id: string;
  name: string;
  transport_type: "usb" | "tcp" | "simulated";
  connection_params: Record<string, unknown>;
}
/** "+ Añadir gateway" → "Crear un contenedor nuevo": pide al lanzador crear
 * el contenedor y persiste el enlace como container_managed (ADR 0028). */
export const createGateway = (body: CreateGatewayIn) => send<GatewayOut>("POST", "/gateways", body);

export const discoverDevices = (gatewayId: string) =>
  send<DeviceOut[]>("POST", `/gateways/${encodeURIComponent(gatewayId)}/discover`);
export const testGatewayConnection = (
  gatewayId: string,
  body: { transport_type: string; connection_params: Record<string, unknown> },
) => send<TestConnectionResultOut>("POST", `/gateways/${encodeURIComponent(gatewayId)}/test-connection`, body);
export const configureGateway = (
  gatewayId: string,
  body: {
    name: string;
    transport_type: string;
    connection_params: Record<string, unknown>;
    enabled?: boolean;
    priority?: number;
  },
) => send<GatewayOut>("POST", `/gateways/${encodeURIComponent(gatewayId)}/configure`, body);
export const importGateway = (gatewayId: string) =>
  send<GatewayOut>("POST", `/gateways/${encodeURIComponent(gatewayId)}/import`);
export const updateGateway = (
  gatewayId: string,
  body: Partial<{
    name: string;
    transport_type: string;
    connection_params: Record<string, unknown>;
    enabled: boolean;
    priority: number;
  }>,
) => send<GatewayOut>("PUT", `/gateways/${encodeURIComponent(gatewayId)}`, body);
export const connectGateway = (gatewayId: string) =>
  send<GatewayOut>("POST", `/gateways/${encodeURIComponent(gatewayId)}/connect`);
export const disconnectGateway = (gatewayId: string) =>
  send<GatewayOut>("POST", `/gateways/${encodeURIComponent(gatewayId)}/disconnect`);
export const deleteGateway = (gatewayId: string) =>
  send<void>("DELETE", `/gateways/${encodeURIComponent(gatewayId)}`);

// ── Organización de nodos (M1.2) ─────────────────────────────────────────────
// Nota: estos endpoints usan `send`, definida más abajo en este módulo.
export const setNodeFavorite = (id: string, value: boolean) =>
  send<NodeOut>("PUT", `/nodes/${encodeURIComponent(id)}/favorite`, { value });
export const setFavoriteBulk = (nodeIds: string[], value: boolean) =>
  send<{ changed: number; unchanged: number }>("POST", "/nodes/bulk-favorite", { node_ids: nodeIds, value });
export const setNodeIgnored = (id: string, value: boolean) =>
  send<NodeOut>("PUT", `/nodes/${encodeURIComponent(id)}/ignored`, { value });
export const setNodeNexus = (id: string, value: boolean) =>
  send<NodeOut>("PUT", `/nodes/${encodeURIComponent(id)}/nexus`, { value });
export const setNodeTags = (id: string, tag_ids: number[]) =>
  send<void>("PUT", `/nodes/${encodeURIComponent(id)}/tags`, { tag_ids });
// Borrado real e irreversible (distinto de setNodeIgnored, que solo lo
// oculta): la fila del nodo + su historial propio desaparecen.
export const deleteNode = (id: string) => send<void>("DELETE", `/nodes/${encodeURIComponent(id)}`);
export interface NodeBulkDeleteOut {
  deleted: number;
}
export const deleteNodesBulk = (nodeIds: string[]) =>
  send<NodeBulkDeleteOut>("DELETE", `/nodes/bulk`, { node_ids: nodeIds });
export const fetchTags = () => get<TagOut[]>("/tags");
export const createTag = (name: string, color?: string) =>
  send<TagOut>("POST", "/tags", { name, color });
export const deleteTag = (id: number) => send<void>("DELETE", `/tags/${id}`);
export const fetchGroups = () => get<GroupOut[]>("/groups");
export const ensureMyGroup = () => send<GroupOut>("POST", "/groups/mine");
export const createGroup = (name: string) => send<GroupOut>("POST", "/groups", { name });
export const deleteGroup = (id: number) => send<void>("DELETE", `/groups/${id}`);

// ── Mantenimiento de la NodeDB ────────────────────────────────────────────────
export const WIPE_NODES_CONFIRM = "BORRAR NODOS";
export interface WipeNodesOut {
  deleted: number;
  alerts_deleted: number;
  node_scoped_rules_deleted: number;
  admin_operations_deleted: number;
  admin_batches_deleted: number;
  nexus_operations_deleted: number;
  activity_log_deleted: number;
}
export const wipeAllNodes = () =>
  send<WipeNodesOut>("DELETE", "/nodes", { confirm: WIPE_NODES_CONFIRM });

// ── Exportar/importar configuración portable a otra instalación ─────────────
// Alcance: reglas de alerta (globales o por grupo, nunca por nodo) +
// canales/integraciones de notificación, perfiles de configuración,
// definiciones de grupos/etiquetas, ajustes de Nexus. NO incluye gateways,
// nodos/NodeDB ni historial — eso es específico de esta instalación.
export const fetchConfigExport = () => get<Record<string, unknown>>("/config/export");
export interface ConfigImportOut {
  created: Record<string, number>;
  skipped_existing: Record<string, number>;
  skipped_invalid: string[];
}
export const importConfig = (bundle: Record<string, unknown>) =>
  send<ConfigImportOut>("POST", "/config/import", bundle);

// ── Selección inteligente de gateway ─────────────────────────────────────────
// Único schema de selección compartido por operaciones individuales y por
// lotes (Nivel 1 de la jerarquía) — nunca tres implementaciones distintas.
export interface GatewaySelectionIn {
  mode: "auto" | "preferred" | "forced";
  gateway_id?: string | null;
}
export const GATEWAY_SELECTION_AUTO: GatewaySelectionIn = { mode: "auto" };
export const GATEWAY_SELECTION_PREFERRED: GatewaySelectionIn = { mode: "preferred" };

export const setNodePreferredGateway = (id: string, gatewayId: string | null) =>
  send<NodeOut>("PUT", `/nodes/${encodeURIComponent(id)}/preferred-gateway`, { gateway_id: gatewayId });
export const setNodeTypeOverride = (id: string, nodeType: string | null) =>
  send<NodeOut>("PUT", `/nodes/${encodeURIComponent(id)}/node-type`, { node_type: nodeType });
export interface NodeTypeBulkOut {
  updated: number;
}
export const setNodeTypeOverrideBulk = (nodeIds: string[], nodeType: string | null) =>
  send<NodeTypeBulkOut>("PUT", `/nodes/node-type/bulk`, { node_ids: nodeIds, node_type: nodeType });
export const setGroupPreferredGateway = (id: number, gatewayId: string | null) =>
  send<GroupOut>("PUT", `/groups/${id}/preferred-gateway`, { gateway_id: gatewayId });
export const addGroupMember = (groupId: number, node_id: string) =>
  send<void>("POST", `/groups/${groupId}/members`, { node_id });
export const removeGroupMember = (groupId: number, nodeId: string) =>
  send<void>("DELETE", `/groups/${groupId}/members/${encodeURIComponent(nodeId)}`);

export interface BulkMembersOut {
  added: number;
  already_member: number;
}
export interface BulkRemoveOut {
  removed: number;
  not_member: number;
}
/** Gestión masiva de grupos desde Flota: un solo viaje, sin importar el tamaño de la selección. */
export const addGroupMembersBulk = (groupId: number, nodeIds: string[]) =>
  send<BulkMembersOut>("POST", `/groups/${groupId}/members/bulk`, { node_ids: nodeIds });
export const removeGroupMembersBulk = (groupId: number, nodeIds: string[]) =>
  send<BulkRemoveOut>("POST", `/groups/${groupId}/members/bulk-remove`, { node_ids: nodeIds });

export const addTagBulk = (tagId: number, nodeIds: string[]) =>
  send<BulkMembersOut>("POST", `/tags/${tagId}/nodes/bulk`, { node_ids: nodeIds });
export const removeTagBulk = (tagId: number, nodeIds: string[]) =>
  send<BulkRemoveOut>("POST", `/tags/${tagId}/nodes/bulk-remove`, { node_ids: nodeIds });

export interface ThresholdsOut {
  low_battery_percent: number;
  offline_minutes_warning: number;
  offline_percent_warning: number;
  offline_percent_critical: number;
  snr_degraded_db: number;
  node_offline_after_seconds: number;
  node_offline_alert_enabled: boolean;
}

export type CriticalReason = "low_battery" | "inactive" | "degraded_snr";

export interface CriticalNodeOut {
  node_id: string;
  short_name: string | null;
  long_name: string | null;
  reasons: CriticalReason[];
  battery_level: number | null;
  snr: number | null;
  last_seen_at: string | null;
  online: boolean;
}

export interface DashboardSummaryOut {
  status: "HEALTHY" | "WARNING" | "CRITICAL";
  generated_at: string;
  nodes_total: number;
  nodes_online: number;
  nodes_offline: number;
  offline_percent: number;
  gateways_total: number;
  gateways_connected: number;
  low_battery_count: number;
  avg_battery_percent: number | null;
  avg_seconds_since_last_seen: number | null;
  events_last_hour: number;
  avg_snr: number | null;
  avg_rssi: number | null;
  avg_channel_utilization: number | null;
  avg_temperature_c: number | null;
  avg_pressure_hpa: number | null;
  critical_nodes: CriticalNodeOut[];
  gateways: GatewayOut[];
  thresholds: ThresholdsOut;
}

export const fetchDashboardSummary = () => get<DashboardSummaryOut>("/dashboard/summary");

// ── Estadísticas curiosas de la malla ────────────────────────────────────────

export interface StatRecordOut {
  key: string;
  label: string;
  icon: string;
  unit: string | null;
  node_id: string;
  short_name: string | null;
  long_name: string | null;
  value: number;
}

export interface StatsSummaryOut {
  generated_at: string;
  nodes_total: number;
  nodes_online: number;
  network_age_days: number | null;
  window_hours: number;
  events_in_window: number;
  records: StatRecordOut[];
}

/** `hours`: ventana del Top, 1..168 (máximo 1 semana). */
export const fetchStatsSummary = (hours = 24, groupId?: number | null) =>
  get<StatsSummaryOut>(`/stats/summary?hours=${hours}${groupId != null ? `&group_id=${groupId}` : ""}`);
/** Ranking completo de un récord (todos los nodos con dato, mejor primero) —
 * "nodos por debajo del top" al desplegar una tarjeta de Estadísticas. */
export const fetchStatsRanking = (key: string, hours = 24, groupId?: number | null) =>
  get<StatRecordOut[]>(
    `/stats/ranking/${encodeURIComponent(key)}?hours=${hours}${groupId != null ? `&group_id=${groupId}` : ""}`,
  );

export type Severity = "INFO" | "WARNING" | "CRITICAL";

export interface AlertOut {
  id: number;
  rule_id: number;
  rule_name: string;
  subject_type: "node" | "gateway" | "system";
  subject_id: string;
  severity: Severity;
  status: "firing" | "acknowledged" | "resolved";
  message: string;
  correlation_key: string | null;
  fired_at: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  resolved_at: string | null;
}

export interface AlertRuleOut {
  id: number;
  name: string;
  rule_type: string;
  severity: Severity;
  enabled: boolean;
  threshold: number | null;
  duration_seconds: number | null;
  cooldown_seconds: number;
  params: Record<string, unknown>;
  /** Reglas por grupo (§1.3): null = regla global. Solo se fija al crear. */
  group_id: number | null;
  /** Reglas por nodo individual: mutuamente excluyente con group_id. Solo
   * se fija al crear (igual que group_id). */
  node_id: string | null;
  /** Canales lógicos a los que despacha esta regla; vacío = todas las
   * integraciones activas (broadcast, comportamiento por defecto). */
  channel_ids: number[];
}

/** Instancia de proveedor configurada — "Integración" en la UI (antes
 * "canal" en el backend de Fase 3C; el nombre cambió al introducir el
 * Canal lógico, ver ChannelOut más abajo). */
export interface ProviderOut {
  id: number;
  name: string;
  provider: string;
  configuration: Record<string, unknown>;
  enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
}

/** Canal lógico (p.ej. "Operadores", "Guardia") que agrupa 1+ integraciones
 * y al que las reglas pueden apuntar. */
export interface ChannelOut {
  id: number;
  name: string;
  description: string | null;
  provider_ids: number[];
  created_at: string | null;
  updated_at: string | null;
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) unauthorizedListener?.();
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${detail || path}`);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const fetchAlerts = (status?: string, limit = 100) =>
  get<AlertOut[]>(`/alerts?limit=${limit}${status ? `&status=${status}` : ""}`);
/** Todas las alertas activas (firing+acknowledged) sin límite — mismo criterio
 * que fetchAlertCounts: una alerta activa antigua nunca debe caer fuera de
 * una ventana truncada. `fetchAlerts(undefined, n)` NO sirve para esto: ordena
 * por fired_at entre todos los estados, así que alertas resueltas recientes
 * (flapping) pueden desplazar a las activas antiguas fuera del límite. */
export const fetchActiveAlerts = () => get<AlertOut[]>("/alerts/active");
export const ackAlert = (id: number) => send<AlertOut>("POST", `/alerts/${id}/ack`);
export const resolveAlert = (id: number) => send<AlertOut>("POST", `/alerts/${id}/resolve`);

/** Agregados reales de alertas activas (hardening): la fuente de los
 * contadores del HUD/StatusBar/insignias — nunca una lista truncada. */
export interface AlertCountsOut {
  active: number;
  firing: number;
  acknowledged: number;
  critical_active: number;
}
export const fetchAlertCounts = (groupId?: number | null) =>
  get<AlertCountsOut>(`/alerts/counts${groupId != null ? `?group_id=${groupId}` : ""}`);
export const fetchAlertRules = () => get<AlertRuleOut[]>("/alert-rules");
export const createAlertRule = (body: Omit<AlertRuleOut, "id">) => send<AlertRuleOut>("POST", "/alert-rules", body);
export const patchAlertRule = (id: number, changes: Partial<AlertRuleOut>) =>
  send<AlertRuleOut>("PATCH", `/alert-rules/${id}`, changes);
export const deleteAlertRule = (id: number) => send<void>("DELETE", `/alert-rules/${id}`);
// ── Integraciones (instancias de proveedor: webhook/ntfy/telegram) ─────────
export const fetchProviders = () => get<ProviderOut[]>("/notification-providers");
export const createProvider = (body: { name: string; provider: string; configuration: Record<string, unknown>; enabled: boolean }) =>
  send<ProviderOut>("POST", "/notification-providers", body);
export const patchProvider = (id: number, changes: Partial<Pick<ProviderOut, "name" | "configuration" | "enabled">>) =>
  send<ProviderOut>("PATCH", `/notification-providers/${id}`, changes);
export const deleteProvider = (id: number) => send<void>("DELETE", `/notification-providers/${id}`);
export const testProvider = (id: number) => send<{ status: string }>("POST", `/notification-providers/${id}/test`);
export const duplicateProvider = (id: number) => send<ProviderOut>("POST", `/notification-providers/${id}/duplicate`);

// ── Canales lógicos (agrupan integraciones; las reglas apuntan a estos) ────
export const fetchChannels = () => get<ChannelOut[]>("/notification-channels");
export const createChannel = (body: { name: string; description?: string | null; provider_ids: number[] }) =>
  send<ChannelOut>("POST", "/notification-channels", body);
export const patchChannel = (id: number, changes: Partial<Pick<ChannelOut, "name" | "description" | "provider_ids">>) =>
  send<ChannelOut>("PATCH", `/notification-channels/${id}`, changes);
export const deleteChannel = (id: number) => send<void>("DELETE", `/notification-channels/${id}`);

export type OperationStatus =
  | "pending"
  | "queued"
  | "running"
  | "succeeded"
  | "succeeded_unconfirmed"
  | "verify_failed"
  | "failed"
  | "timeout"
  | "cancelled";

export interface ParamFieldOut {
  name: string;
  kind: "string" | "number";
  required: boolean;
  max_length: number | null;
  minimum: number | null;
  maximum: number | null;
}

export interface CapabilityOut {
  operation_type: string;
  description: string;
  kind: string;
  allow_bulk: boolean;
  destructive: boolean;
  required_role: string;
  requires_confirmation: boolean;
  param_choices: Record<string, string[]>;
  param_fields: ParamFieldOut[];
  ack_only: boolean;
}

export interface OperationOut {
  id: number;
  batch_id: number | null;
  target_node_id: string;
  gateway_id: string;
  operation_type: string;
  params: Record<string, unknown>;
  status: OperationStatus;
  priority: number;
  attempts: number;
  max_attempts: number;
  timeout_seconds: number;
  result: Record<string, unknown> | null;
  error: string | null;
  created_by: string;
  created_at: string | null;
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  gateway_note: string | null;
  /** Resuelto en backend (resolve_actor_label): nunca reconstruir en React. */
  actor_label: string;
}

export const fetchCapabilities = () => get<CapabilityOut[]>("/admin/capabilities");
export const fetchOperations = (status?: string, limit = 100) =>
  get<OperationOut[]>(`/admin/operations?limit=${limit}${status ? `&status=${status}` : ""}`);

/** Agregados reales de operaciones no terminales (hardening) — misma
 * filosofía que fetchAlertCounts. */
export interface OperationCountsOut {
  pending: number;
  queued: number;
  running: number;
  active: number;
}
export const fetchOperationCounts = (groupId?: number | null) =>
  get<OperationCountsOut>(`/admin/operations/counts${groupId != null ? `?group_id=${groupId}` : ""}`);
export const createOperation = (body: {
  node_id: string;
  operation_type: string;
  params?: Record<string, unknown>;
  gateway_selection?: GatewaySelectionIn;
}) => send<OperationOut>("POST", "/admin/operations", body);
export const cancelOperation = (id: number) => send<OperationOut>("POST", `/admin/operations/${id}/cancel`);
export const retryOperation = (id: number) => send<OperationOut>("POST", `/admin/operations/${id}/retry`);

// ── Favoritos/ignorados remotos (M4.1/M4.2) ─────────────────────────────────
// "confirmado" = el firmware aceptó el AdminMessage (ACK); el NOC no puede
// releer la NodeDB remota para verificarlo de verdad (ADR 0019).
export type RemoteFlagSyncState = "pending" | "sent" | "confirmed" | "error";
export type RemoteFlagType = "favorite" | "ignored";

export interface RemoteFlagKnownOut {
  subject_node_id: string;
  subject_display_name: string | null;
  latest_action: "set" | "remove";
  sync_state: RemoteFlagSyncState;
  operation_id: number;
  updated_at: string | null;
}

export const fetchKnownRemoteFlags = (nodeId: string, flagType: RemoteFlagType) =>
  get<RemoteFlagKnownOut[]>(
    `/admin/remote-flags/${encodeURIComponent(nodeId)}/known?flag_type=${flagType}`,
  );

export const queueRemoteFlag = (
  nodeId: string,
  body: { flag_type: RemoteFlagType; action: "set" | "remove"; subject_node_id: string; send_contact: boolean },
) => send<{ batch_id: number; operation_type: string; node_ids: string[] }>(
  "POST",
  `/admin/remote-flags/${encodeURIComponent(nodeId)}/queue`,
  body,
);

export interface RemoteFlagSyncOut {
  batch_id: number | null;
  operation_type: string;
  node_ids: string[];
  items: number;
}

export const syncRemoteFlags = (nodeId: string, body: { flag_type: RemoteFlagType; send_contact: boolean }) =>
  send<RemoteFlagSyncOut>("POST", `/admin/remote-flags/${encodeURIComponent(nodeId)}/sync`, body);

export const resendPendingRemoteFlags = (nodeId: string, flagType: RemoteFlagType) =>
  send<RemoteFlagSyncOut>("POST", `/admin/remote-flags/${encodeURIComponent(nodeId)}/resend-pending`, {
    flag_type: flagType,
    send_contact: false,
  });

// ── Editor de configuración (M1.4) ──────────────────────────────────────────

export type FieldKind = "bool" | "int" | "float" | "str" | "enum" | "message" | "bytes" | "unknown";

export interface ConfigFieldSchema {
  name: string;
  kind: FieldKind;
  enum_values: string[];
  repeated: boolean;
  submessage: string | null;
  editable: boolean;
  description: string;
}

export interface ConfigSectionSchema {
  name: string;
  display_name: string;
  kind: "config" | "module_config" | "owner";
  risk: "SAFE" | "WARNING" | "DANGEROUS";
  description: string;
  fields: ConfigFieldSchema[];
}

export interface ConfigSchemaOut {
  ui_groups: Record<string, string[]>;
  sections: ConfigSectionSchema[];
}

export interface SectionSnapshot {
  section: string;
  kind: "config" | "module_config" | "owner";
  values: Record<string, unknown>;
  last_read_at: string | null;
  last_operation_id: number | null;
}

export interface ConfigStateOut {
  node_id: string;
  sections: SectionSnapshot[];
}

export const fetchConfigSchema = () => get<ConfigSchemaOut>("/admin/config/schema");
export const fetchNodeConfig = (nodeId: string) =>
  get<ConfigStateOut>(`/nodes/${encodeURIComponent(nodeId)}/config`);
export const refreshNodeConfig = (
  nodeId: string,
  sections?: string[],
  gatewaySelection?: GatewaySelectionIn,
) =>
  send<{ operation_ids: number[]; gateway_note: string | null }>(
    "POST",
    `/nodes/${encodeURIComponent(nodeId)}/config/refresh`,
    { sections: sections ?? null, gateway_selection: gatewaySelection },
  );
// ── Batch Engine (M2) ────────────────────────────────────────────────────────

export type BatchStatus = "running" | "paused" | "cancelled" | "completed" | "completed_with_errors";

export interface BatchScopeIn extends NodeFilterParams {
  node_ids?: string[];
}

export interface NodePreviewOut {
  node_id: string;
  display_name: string;
  eligible: boolean;
  warnings: string[];
  blockers: string[];
}

export interface BatchPreviewOut {
  operation_type: string;
  params: Record<string, unknown>;
  total_selected: number;
  eligible_count: number;
  excluded_count: number;
  eligible: NodePreviewOut[];
  excluded: NodePreviewOut[];
  requires_verification: boolean;
  estimated_seconds: number;
  scope_description: Record<string, unknown>;
}

export interface BatchOut {
  id: number;
  name: string;
  operation_type: string;
  params: Record<string, unknown>;
  node_count: number;
  status: BatchStatus;
  created_by: string;
  actor_label: string;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface BatchProgressOut {
  counts: Record<string, number>;
  total: number;
  done: number;
  percent: number;
  current_node_id: string | null;
  rate_per_minute: number | null;
  eta_seconds: number;
  elapsed_seconds: number;
}

export interface BatchDetailOut extends BatchOut {
  node_ids: string[];
  scope_description: Record<string, unknown> | null;
  progress: BatchProgressOut;
}

export const previewBatch = (body: {
  operation_type: string;
  params: Record<string, unknown>;
  scope: BatchScopeIn;
  // Hardening: la simulación viaja con la MISMA selección de gateway que la
  // ejecución — el dry-run nunca puede divergir de lo que se va a ejecutar.
  gateway_selection?: GatewaySelectionIn;
}) => send<BatchPreviewOut>("POST", "/admin/batches/preview", body);
export const createBatch = (body: {
  name: string;
  operation_type: string;
  params: Record<string, unknown>;
  node_ids: string[];
  scope_description?: Record<string, unknown>;
  gateway_selection?: GatewaySelectionIn;
}) => send<BatchOut>("POST", "/admin/batches", body);
export function fetchBatches(filters: {
  status?: string;
  operation_type?: string;
  node_id?: string;
  limit?: number;
} = {}): Promise<BatchOut[]> {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== "") params.set(k, String(v));
  }
  const qs = params.toString();
  return get<BatchOut[]>(`/admin/batches${qs ? `?${qs}` : ""}`);
}
export const fetchBatch = (id: number) => get<BatchDetailOut>(`/admin/batches/${id}`);
export const fetchBatchOperations = (id: number, status?: string, limit = 500) =>
  get<OperationOut[]>(
    `/admin/batches/${id}/operations?limit=${limit}${status ? `&status=${status}` : ""}`,
  );
export const pauseBatch = (id: number) => send<BatchOut>("POST", `/admin/batches/${id}/pause`);
export const resumeBatch = (id: number) => send<BatchOut>("POST", `/admin/batches/${id}/resume`);
export const cancelBatch = (id: number) => send<BatchOut>("POST", `/admin/batches/${id}/cancel`);

export const applyNodeConfig = (
  nodeId: string,
  sections: Record<string, Record<string, unknown>>,
  gatewaySelection?: GatewaySelectionIn,
) =>
  send<{ operation_ids: number[]; gateway_note: string | null }>(
    "POST",
    `/nodes/${encodeURIComponent(nodeId)}/config/apply`,
    { sections, gateway_selection: gatewaySelection },
  );

// ── Perfiles de configuración (M3) ───────────────────────────────────────────

export type ProfileSections = Record<string, Record<string, unknown>>;

export interface ProfileOut {
  id: number;
  name: string;
  description: string | null;
  latest_version: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface ProfileDetailOut extends ProfileOut {
  sections: ProfileSections;
}

export interface ProfileVersionOut {
  id: number;
  profile_id: number;
  version: number;
  sections: ProfileSections;
  comment: string | null;
  created_by: string;
  created_at: string | null;
}

export type DiffStatus = "equal" | "different" | "unknown";

export interface FieldDiffOut {
  field: string;
  kind: string;
  profile_value: unknown;
  node_value: unknown;
  status: DiffStatus;
}

export interface SectionDiffOut {
  section: string;
  risk: "SAFE" | "WARNING" | "DANGEROUS";
  has_snapshot: boolean;
  last_read_at: string | null;
  fields: FieldDiffOut[];
}

export interface CompareOut {
  profile_id: number;
  version: number;
  node_id: string;
  sections: SectionDiffOut[];
  equal_count: number;
  different_count: number;
  unknown_count: number;
}

export interface NodeSyncPlanOut {
  node_id: string;
  display_name: string;
  eligible: boolean;
  sections_to_apply: ProfileSections;
  change_count: number;
  equal_count: number;
  unknown_sections: string[];
  warnings: string[];
  blockers: string[];
}

export interface SyncPreviewOut {
  profile_id: number;
  profile_name: string;
  version: number;
  include_unknown: boolean;
  eligible: NodeSyncPlanOut[];
  excluded: NodeSyncPlanOut[];
  total_operations: number;
  estimated_seconds: number;
}

export interface SyncIn {
  node_ids: string[];
  version?: number;
  include_unknown?: boolean;
  name?: string;
}

export const fetchProfiles = () => get<ProfileOut[]>("/admin/profiles");
export const fetchProfile = (id: number) => get<ProfileDetailOut>(`/admin/profiles/${id}`);
export const createProfile = (body: { name: string; description?: string; sections: ProfileSections }) =>
  send<ProfileDetailOut>("POST", "/admin/profiles", body);
export const patchProfile = (id: number, body: { name?: string; description?: string }) =>
  send<ProfileOut>("PATCH", `/admin/profiles/${id}`, body);
export const deleteProfile = (id: number) => send<void>("DELETE", `/admin/profiles/${id}`);
export const fetchProfileVersions = (id: number) =>
  get<ProfileVersionOut[]>(`/admin/profiles/${id}/versions`);
export const createProfileVersion = (id: number, sections: ProfileSections, comment?: string) =>
  send<ProfileVersionOut>("POST", `/admin/profiles/${id}/versions`, { sections, comment });
export const compareProfile = (id: number, nodeId: string, version?: number) =>
  get<CompareOut>(
    `/admin/profiles/${id}/compare/${encodeURIComponent(nodeId)}${version ? `?version=${version}` : ""}`,
  );
export const previewProfileSync = (id: number, body: SyncIn) =>
  send<SyncPreviewOut>("POST", `/admin/profiles/${id}/sync/preview`, body);
export const syncProfile = (id: number, body: SyncIn) =>
  send<BatchOut>("POST", `/admin/profiles/${id}/sync`, body);

export interface NocEvent {
  schema_version: number;
  event_type: string;
  event_id: string;
  gateway_id: string;
  timestamp: string;
  payload: Record<string, unknown>;
}

/** Entrada del Registro persistente (hardening): el mismo envelope
 * `activity.event` del WS más su `log_id` para paginar hacia atrás. */
export interface ActivityLogItemOut extends NocEvent {
  log_id: number;
}

export function fetchActivityLog(
  limit = 300,
  opts: {
    beforeId?: number;
    nodeId?: string;
    source?: string;
    gatewayId?: string;
    groupId?: number | null;
    q?: string;
    internalType?: string;
  } = {},
): Promise<ActivityLogItemOut[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (opts.beforeId != null) params.set("before_id", String(opts.beforeId));
  if (opts.nodeId) params.set("node_id", opts.nodeId);
  if (opts.source) params.set("source", opts.source);
  if (opts.gatewayId) params.set("gateway_id", opts.gatewayId);
  if (opts.groupId != null) params.set("group_id", String(opts.groupId));
  if (opts.q) params.set("q", opts.q);
  if (opts.internalType) params.set("internal_type", opts.internalType);
  return get<ActivityLogItemOut[]>(`/activity?${params}`);
}

/**
 * Chat: monitor de TEXT_MESSAGE_APP (mismo paquete que Actividad, tabla
 * propia con columnas estructuradas para el selector de canales/DM).
 */
export interface ChatMessageOut {
  id: number;
  from_node_id: string;
  to_node_id: string | null;
  channel_index: number;
  channel_name: string | null;
  text: string;
  gateway_id: string | null;
  rssi: number | null;
  snr: number | null;
  hops_away: number | null;
  hop_limit: number | null;
  hop_start: number | null;
  packet_id: number | null;
  direction: string;
  received_at: string | null;
}

export function fetchChatMessages(
  limit = 100,
  opts: {
    beforeId?: number;
    channelIndex?: number;
    dmOnly?: boolean;
    broadcastOnly?: boolean;
    nodeId?: string;
    gatewayId?: string;
    q?: string;
  } = {},
): Promise<ChatMessageOut[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (opts.beforeId != null) params.set("before_id", String(opts.beforeId));
  if (opts.channelIndex != null) params.set("channel_index", String(opts.channelIndex));
  if (opts.dmOnly) params.set("dm_only", "true");
  if (opts.broadcastOnly) params.set("broadcast_only", "true");
  if (opts.nodeId) params.set("node_id", opts.nodeId);
  if (opts.gatewayId) params.set("gateway_id", opts.gatewayId);
  if (opts.q) params.set("q", opts.q);
  return get<ChatMessageOut[]>(`/chat/messages?${params}`);
}

export interface ChatChannelOut {
  channel_index: number;
  channel_name: string | null;
  message_count: number;
  last_message_at: string | null;
}

export interface ChatGatewayChannelsOut {
  gateway_id: string;
  channels: ChatChannelOut[];
  dm_count: number;
}

export interface ChatChannelsOut {
  channels: ChatChannelOut[];
  dm_count: number;
  by_gateway: ChatGatewayChannelsOut[];
}

export const fetchChatChannels = () => get<ChatChannelsOut>("/chat/channels");

/**
 * Estado de la conexión de eventos, de primera clase para la UI (v0.7 §11.2):
 * antes el socket moría en silencio y la interfaz se quedaba congelada sin
 * avisar. `disconnectedAt` permite mostrar "datos congelados desde HH:MM:SS".
 */
export interface EventsSocketStatus {
  state: "connecting" | "connected" | "reconnecting";
  /** Instante de la última desconexión (null si nunca se ha caído). */
  disconnectedAt: Date | null;
}

export interface EventsSocketHandle {
  close: () => void;
}

export const AUTH_CHANGED_EVENT = "ms:auth-changed";

export function openEventsSocket(
  onEvent: (e: NocEvent) => void,
  onStatus?: (s: EventsSocketStatus) => void,
): EventsSocketHandle {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${window.location.host}/ws/events`;
  let ws: WebSocket | null = null;
  let closedByClient = false;
  let retryTimer: number | null = null;
  let retryDelayMs = 1_000;
  let everConnected = false;
  let disconnectedAt: Date | null = null;

  const connect = () => {
    onStatus?.({ state: everConnected ? "reconnecting" : "connecting", disconnectedAt });
    ws = new WebSocket(url);
    ws.onopen = () => {
      everConnected = true;
      retryDelayMs = 1_000;
      disconnectedAt = null;
      onStatus?.({ state: "connected", disconnectedAt: null });
    };
    ws.onmessage = (msg) => {
      try {
        onEvent(JSON.parse(msg.data));
      } catch {
        // evento malformado: se ignora
      }
    };
    // onerror siempre viene seguido de onclose: la reconexión vive solo ahí
    ws.onclose = () => {
      if (closedByClient) return;
      if (disconnectedAt == null) disconnectedAt = new Date();
      onStatus?.({ state: "reconnecting", disconnectedAt });
      retryTimer = window.setTimeout(() => {
        retryTimer = null;
        connect();
      }, retryDelayMs);
      retryDelayMs = Math.min(retryDelayMs * 2, 30_000);
    };
  };

  // Tras iniciar/cerrar sesión el canal puede haber sido rechazado (ajuste
  // "exigir sesión"): reconectar YA en vez de esperar al backoff de hasta 30 s
  const onAuthChanged = () => {
    if (closedByClient || ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING) return;
    if (retryTimer != null) window.clearTimeout(retryTimer);
    retryTimer = null;
    retryDelayMs = 1_000;
    connect();
  };
  window.addEventListener(AUTH_CHANGED_EVENT, onAuthChanged);

  connect();
  return {
    close: () => {
      window.removeEventListener(AUTH_CHANGED_EVENT, onAuthChanged);
      closedByClient = true;
      if (retryTimer != null) window.clearTimeout(retryTimer);
      ws?.close();
    },
  };
}

// ── Autenticación ────────────────────────────────────────────────────────────
// Monitorización siempre abierta; estos endpoints son los únicos que exigen
// sesión (login/gestión de usuarios) o la usan si existe (me/login-log).

export type UserRole = "admin" | "manager" | "user";

export interface AuthUserOut {
  id: number;
  username: string;
  display_name: string;
  role: UserRole;
  is_admin: boolean;
  enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
  last_login_at: string | null;
}

export interface MeOut {
  authenticated: boolean;
  protected_mode: boolean;
  user: AuthUserOut | null;
}

export const fetchMe = () => get<MeOut>("/auth/me");
export const login = (username: string, password: string) =>
  send<AuthUserOut>("POST", "/auth/login", { username, password });
export const logout = () => send<void>("POST", "/auth/logout");
export const updateMyDisplayName = (display_name: string) =>
  send<AuthUserOut>("PATCH", "/auth/me", { display_name });
export const changeMyPassword = (password: string) => send<void>("PUT", "/auth/me/password", { password });

// ── Gestión de usuarios (solo is_admin en el backend; sin más RBAC) ─────────

export const fetchUsers = () => get<AuthUserOut[]>("/auth/users");
export const createUser = (body: { username: string; display_name: string; password: string; role: UserRole }) =>
  send<AuthUserOut>("POST", "/auth/users", body);
export const updateUser = (id: number, body: { display_name?: string; role?: UserRole }) =>
  send<AuthUserOut>("PUT", `/auth/users/${id}`, body);
export const setUserEnabled = (id: number, enabled: boolean) =>
  send<AuthUserOut>("PUT", `/auth/users/${id}/enabled`, { enabled });
export const setUserPassword = (id: number, password: string) =>
  send<void>("PUT", `/auth/users/${id}/password`, { password });
export const deleteUser = (id: number) => send<void>("DELETE", `/auth/users/${id}`);

// ── Login log (solo lectura, paginado) ──────────────────────────────────────

export interface LoginLogEntryOut {
  id: number;
  user_id: number | null;
  username: string;
  event: string;
  reason: string | null;
  ip: string | null;
  user_agent: string | null;
  created_at: string | null;
}

export const fetchLoginLog = (limit = 100, beforeId?: number | null) =>
  get<LoginLogEntryOut[]>(`/auth/login-log?limit=${limit}${beforeId != null ? `&before_id=${beforeId}` : ""}`);

// ── Ajustes (umbrales operacionales editables sin redeploy, solo admin) ────

export interface SettingOut {
  key: string;
  category: string;
  category_label: string;
  label: string;
  description: string;
  value_type: "int" | "float";
  unit: string | null;
  min_value: number | null;
  default_value: number;
  value: number;
  overridden: boolean;
  choices: [string, number][] | null;
}

export const fetchSettings = () => get<SettingOut[]>("/settings");
export const patchSetting = (key: string, value: number) =>
  send<SettingOut>("PATCH", `/settings/${encodeURIComponent(key)}`, { value });
export const resetSetting = (key: string) => send<SettingOut>("DELETE", `/settings/${encodeURIComponent(key)}`);

// ── JenTastic-Nexus (ADR 0027) ───────────────────────────────────────────────
// El interruptor global gatea el módulo entero; la detección SOLO sugiere —
// el marcado (setNodeNexus, arriba) es un paso aparte, siempre confirmado
// por el operador.

export interface NexusModeOut {
  enabled: boolean;
}

export interface NexusCandidateOut {
  node_id: string;
  short_name: string | null;
  version: string | null;
  role: string | null;
  marker: string | null;
  already_marked: boolean;
}

export interface NexusScanOut {
  candidates: NexusCandidateOut[];
}

export const fetchNexusMode = () => get<NexusModeOut>("/nexus/mode");
export const setNexusMode = (enabled: boolean) => send<NexusModeOut>("PUT", "/nexus/mode", { enabled });
export const scanForNexusNodes = (gatewayId: string, windowSeconds = 30) =>
  send<NexusScanOut>("POST", "/nexus/scan", { gateway_id: gatewayId, window_seconds: windowSeconds });

// Detección PASIVA: no manda nada, solo observa tráfico ya visto en el
// canal Nexus (el backend escucha message.received en vivo, ver
// nexus_gateway.py). Misma regla que el escaneo activo: solo sugiere.
export interface NexusPassiveCandidateOut {
  node_id: string;
  short_name: string | null;
  gateway_id: string;
  sample_text: string;
  command: string | null;
  first_seen_at: string;
  last_seen_at: string;
  match_count: number;
  already_marked: boolean;
}

export const fetchNexusPassiveCandidates = () =>
  get<NexusPassiveCandidateOut[]>("/nexus/passive-candidates");
export const dismissNexusPassiveCandidate = (nodeId: string) =>
  send<void>("POST", `/nexus/passive-candidates/${encodeURIComponent(nodeId)}/dismiss`);

// ── Cola de operaciones (ADR 0027 §4) ────────────────────────────────────────
// Vocabulario de operador (M4.1): pending/sent/confirmed/no_response — nunca
// el vocabulario del pipeline de administración (modelo distinto: el
// gateway nunca reporta resultado, la correlación es del backend).

export type NexusTargetKind = "broadcast" | "local" | "node" | "device" | "mac" | "group";
export type NexusOperationStatus = "pending" | "sent" | "confirmed" | "no_response";

export interface NexusOperationIn {
  gateway_id: string;
  command: string;
  args?: string[];
  target_kind: NexusTargetKind;
  target_value?: string | null;
}

export interface NexusOperationPreviewOut {
  text: string;
  destructive: boolean;
  requires_save: boolean;
  busy_seconds: number;
}

export interface NexusOperationOut {
  id: number;
  gateway_id: string;
  target_kind: NexusTargetKind;
  target_value: string | null;
  command_name: string;
  args: string[];
  text: string;
  destructive: boolean;
  requires_save: boolean;
  busy_seconds: number;
  status: NexusOperationStatus;
  created_by: string | null;
  created_at: string | null;
  sent_at: string | null;
  response_at: string | null;
  response_text: string | null;
  response_kind: "structured" | "raw" | "unsupported" | null;
  response_data: Record<string, unknown> | null;
}

export const previewNexusOperation = (body: NexusOperationIn) =>
  send<NexusOperationPreviewOut>("POST", "/nexus/operations/preview", body);
export const createNexusOperation = (body: NexusOperationIn) =>
  send<NexusOperationOut>("POST", "/nexus/operations", body);

/** Lote (ADR 0027 §14): una operación `-node <shortname>` por cada nombre
 * en `target_values`, espaciadas entre sí por `interval_seconds` — para
 * "toda la flota" se usa `createNexusOperation` con target_kind=broadcast
 * (ya llega a todos de una), esto es solo para SUBCONJUNTOS seleccionados. */
export interface NexusOperationBatchIn {
  gateway_id: string;
  command: string;
  args?: string[];
  target_values: string[];
  interval_seconds?: number;
}
export const createNexusOperationBatch = (body: NexusOperationBatchIn) =>
  send<NexusOperationOut[]>("POST", "/nexus/operations/batch", body);
export const fetchNexusOperations = (gatewayId?: string, status?: NexusOperationStatus, limit = 100) => {
  const params = new URLSearchParams();
  if (gatewayId) params.set("gateway_id", gatewayId);
  if (status) params.set("status", status);
  params.set("limit", String(limit));
  return get<NexusOperationOut[]>(`/nexus/operations?${params.toString()}`);
};

/** Respuestas individuales de una operación de destino múltiple
 * (broadcast/group, ADR 0027 §11) — vacío para destinos dirigidos. */
export interface NexusOperationResponseOut {
  id: number;
  from_node_id: string;
  received_at: string | null;
  response_text: string;
  response_kind: "structured" | "raw" | "unsupported";
  response_data: Record<string, unknown> | null;
}
export const fetchNexusOperationResponses = (opId: number) =>
  get<NexusOperationResponseOut[]>(`/nexus/operations/${opId}/responses`);

// ── Consola Nexus: chat del canal con respuestas interpretadas ──────────────

export interface NexusInterpretationOut {
  outcome: "ok" | "error" | "info";
  summary: string;
  flag_type: "favorite" | "ignored" | "nign" | null;
  flag_present: boolean | null;
  subject_node_id: string | null;
  data: Record<string, unknown> | null;
}
export interface NexusConversationMessageOut {
  id: number;
  from_node_id: string;
  sender_label: string;
  text: string;
  gateway_id: string | null;
  channel_index: number;
  received_at: string | null;
  rssi: number | null;
  snr: number | null;
  hops_away: number | null;
  context_op_id: number | null;
  interpretation: NexusInterpretationOut | null;
  /** >0: respuesta paginada reensamblada de N mensajes del nodo. */
  parts: number;
}
export interface NexusConversationOut {
  messages: NexusConversationMessageOut[];
  operations: NexusOperationOut[];
  channels: string[];
}
export const fetchNexusConversation = (limit = 200) =>
  get<NexusConversationOut>(`/nexus/conversation?limit=${limit}`);

/** Favoritos/ignorados conocidos de un nodo Nexus (confirmaciones + lecturas). */
export interface NexusKnownFlagOut {
  flag_type: "favorite" | "ignored" | "nign";
  subject_node_id: string;
  subject_label: string;
  subject_short_name: string | null;
  source: "confirmation" | "read";
  updated_at: string | null;
}
export const fetchNexusKnownFlags = (nodeId: string) =>
  get<NexusKnownFlagOut[]>(`/nexus/nodes/${encodeURIComponent(nodeId)}/flags`);

// ── Catálogo (ADR 0027 §12): explorador de comandos, no texto libre ────────

export interface NexusSyntaxArg {
  name: string;
  label: string;
  kind: "choice" | "node" | "number" | "onoff" | "text" | "hex";
  choices: string[];
  min: number | null;
  max: number | null;
  optional: boolean;
  placeholder: string;
  hint: string;
  /** Solo onoff: valores reales enviados (el firmware espera 1/0). */
  on_value: string;
  off_value: string;
}

/** Una forma de invocar el comando: tokens fijos + campos a rellenar. */
export interface NexusSyntaxVariant {
  label: string;
  tokens: string[];
  args: NexusSyntaxArg[];
  note: string;
  /** Probada contra hardware real (prevalece sobre el manual). */
  verified: boolean;
}

export interface NexusCatalogEntryOut {
  name: string;
  category: string;
  aliases: string[];
  mutation: "never" | "always" | "with_args";
  destructive: boolean;
  busy_seconds: number;
  broadcast_forbidden: boolean;
  description: string;
  /** Vacío = sin sintaxis modelada: el asistente cae a texto libre. */
  syntax: NexusSyntaxVariant[];
}
export const fetchNexusCatalog = () => get<NexusCatalogEntryOut[]>("/nexus/catalog");

// ── Ajustes del módulo (ADR 0027 §13) ───────────────────────────────────────

export type NexusAddressingMode = "shortname" | "device_id";

export interface NexusPinnedNode {
  short_name: string;
  label: string;
}

export interface NexusTemplate {
  label: string;
  command: string;
  args: string;
}

export interface NexusSettingsOut {
  addressing_mode: NexusAddressingMode;
  command_prefix: string;
  channel_name: string | null;
  response_window_seconds: number;
  scan_cooldown_seconds: number;
  passive_detection_enabled: boolean;
  default_target_kind: NexusTargetKind;
  default_gateway_id: string | null;
  catalog_collapsed_default: boolean;
  notify_on_broadcast_complete: boolean;
  hidden_commands: string[];
  pinned_nodes: NexusPinnedNode[];
  templates: NexusTemplate[];
}

export const fetchNexusSettings = () => get<NexusSettingsOut>("/nexus/settings");
export const patchNexusSettings = (changes: Partial<NexusSettingsOut>) =>
  send<NexusSettingsOut>("PATCH", "/nexus/settings", changes);

// Grupo de arranque: ajuste GLOBAL de la app ("last" | "none" | id de grupo).
export type StartupGroup = "last" | "none" | number;
export const fetchStartupGroup = () => get<{ value: StartupGroup }>("/settings/startup-group");
export const setStartupGroup = (value: StartupGroup) =>
  send<{ value: StartupGroup }>("PUT", "/settings/startup-group", { value });

// ── Mantenimiento de datos: almacenamiento, retención y salud del NOC (admin) ──

export interface TableStatsOut {
  table: string;
  label: string;
  rows: number;
  bytes: number | null;
  oldest: string | null;
}

export interface RetentionPolicyOut {
  key: string;
  label: string;
  setting: string;
  days: number;
  tables: string[];
  rows: number;
  bytes: number | null;
  oldest: string | null;
}

export interface RetentionRunOut {
  finished_at: string;
  duration_seconds: number;
  deleted: Record<string, number>;
  trigger: "scheduled" | "manual";
  error: string | null;
}

export interface StorageOut {
  engine: string;
  total_bytes: number | null;
  tables: TableStatsOut[];
  policies: RetentionPolicyOut[];
  last_run: RetentionRunOut | null;
  running: boolean;
}

export interface RuntimeOut {
  uptime_seconds: number;
  ws_clients: number;
  ws_dropped_clients: number;
  activity_queue_size: number;
  activity_queue_max: number;
  activity_dropped: number;
  event_loop_lag_ms: number;
  retention_running: boolean;
}

export const fetchStorage = () => get<StorageOut>("/maintenance/storage");
export const pruneNow = () => send<RetentionRunOut>("POST", "/maintenance/prune");
export const fetchRuntime = () => get<RuntimeOut>("/maintenance/runtime");

export interface DigestSendOut {
  delivered: number;
  providers: number;
}
export const fetchDigestStatus = () => get<{ last_sent_at: string | null }>("/maintenance/digest");
export const sendDigestNow = () => send<DigestSendOut>("POST", "/maintenance/digest/send");

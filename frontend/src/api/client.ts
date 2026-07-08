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
}

export interface NodeSummaryOut {
  node: NodeOut;
  last_position: PositionOut | null;
  last_device_telemetry: TelemetryOut | null;
  tags: TagOut[];
  group_ids: number[];
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
}

export interface GatewayOut {
  gateway_id: string;
  status: string;
  transport: string;
  local_node_id: string | null;
  detail: string | null;
  updated_at: string | null;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api/v1${path}`);
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
export const fetchNodeTelemetry = (id: string, limit = 50) =>
  get<TelemetryOut[]>(`/nodes/${encodeURIComponent(id)}/telemetry?limit=${limit}`);
export const fetchGateways = () => get<GatewayOut[]>("/gateways");

// ── Organización de nodos (M1.2) ─────────────────────────────────────────────
// Nota: estos endpoints usan `send`, definida más abajo en este módulo.
export const setNodeFavorite = (id: string, value: boolean) =>
  send<NodeOut>("PUT", `/nodes/${encodeURIComponent(id)}/favorite`, { value });
export const setNodeIgnored = (id: string, value: boolean) =>
  send<NodeOut>("PUT", `/nodes/${encodeURIComponent(id)}/ignored`, { value });
export const setNodeTags = (id: string, tag_ids: number[]) =>
  send<void>("PUT", `/nodes/${encodeURIComponent(id)}/tags`, { tag_ids });
export const fetchTags = () => get<TagOut[]>("/tags");
export const createTag = (name: string, color?: string) =>
  send<TagOut>("POST", "/tags", { name, color });
export const deleteTag = (id: number) => send<void>("DELETE", `/tags/${id}`);
export const fetchGroups = () => get<GroupOut[]>("/groups");
export const createGroup = (name: string) => send<GroupOut>("POST", "/groups", { name });
export const deleteGroup = (id: number) => send<void>("DELETE", `/groups/${id}`);
export const addGroupMember = (groupId: number, node_id: string) =>
  send<void>("POST", `/groups/${groupId}/members`, { node_id });
export const removeGroupMember = (groupId: number, nodeId: string) =>
  send<void>("DELETE", `/groups/${groupId}/members/${encodeURIComponent(nodeId)}`);

export interface ThresholdsOut {
  low_battery_percent: number;
  offline_minutes_warning: number;
  offline_percent_warning: number;
  offline_percent_critical: number;
  snr_degraded_db: number;
  node_offline_after_seconds: number;
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
  critical_nodes: CriticalNodeOut[];
  gateways: GatewayOut[];
  thresholds: ThresholdsOut;
}

export const fetchDashboardSummary = () => get<DashboardSummaryOut>("/dashboard/summary");

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
}

export interface ChannelOut {
  id: number;
  name: string;
  channel_type: "webhook" | "ntfy";
  config: Record<string, unknown>;
  enabled: boolean;
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${detail || path}`);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const fetchAlerts = (status?: string, limit = 100) =>
  get<AlertOut[]>(`/alerts?limit=${limit}${status ? `&status=${status}` : ""}`);
export const fetchAlertRules = () => get<AlertRuleOut[]>("/alert-rules");
export const patchAlertRule = (id: number, changes: Partial<AlertRuleOut>) =>
  send<AlertRuleOut>("PATCH", `/alert-rules/${id}`, changes);
export const fetchChannels = () => get<ChannelOut[]>("/channels");
export const createChannel = (body: Omit<ChannelOut, "id">) => send<ChannelOut>("POST", "/channels", body);
export const deleteChannel = (id: number) => send<void>("DELETE", `/channels/${id}`);
export const testChannel = (id: number) => send<{ status: string }>("POST", `/channels/${id}/test`);

export type OperationStatus =
  | "pending"
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "timeout"
  | "cancelled";

export interface CapabilityOut {
  operation_type: string;
  description: string;
  kind: string;
  allow_bulk: boolean;
  destructive: boolean;
  required_role: string;
  param_choices: Record<string, string[]>;
}

export interface OperationOut {
  id: number;
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
}

export const fetchCapabilities = () => get<CapabilityOut[]>("/admin/capabilities");
export const fetchOperations = (status?: string, limit = 100) =>
  get<OperationOut[]>(`/admin/operations?limit=${limit}${status ? `&status=${status}` : ""}`);
export const createOperation = (body: {
  node_id: string;
  operation_type: string;
  params?: Record<string, unknown>;
}) => send<OperationOut>("POST", "/admin/operations", body);
export const cancelOperation = (id: number) => send<OperationOut>("POST", `/admin/operations/${id}/cancel`);
export const retryOperation = (id: number) => send<OperationOut>("POST", `/admin/operations/${id}/retry`);

export interface NocEvent {
  schema_version: number;
  event_type: string;
  event_id: string;
  gateway_id: string;
  timestamp: string;
  payload: Record<string, unknown>;
}

export function openEventsSocket(onEvent: (e: NocEvent) => void): WebSocket {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${window.location.host}/ws/events`);
  ws.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data));
    } catch {
      // evento malformado: se ignora
    }
  };
  return ws;
}

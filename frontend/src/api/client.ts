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
  online: boolean;
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

export interface NodeSummaryOut {
  node: NodeOut;
  last_position: PositionOut | null;
  last_device_telemetry: TelemetryOut | null;
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
export const fetchNodes = () => get<NodeSummaryOut[]>("/nodes");
export const fetchNode = (id: string) => get<NodeOut>(`/nodes/${encodeURIComponent(id)}`);
export const fetchNodePositions = (id: string, limit = 50) =>
  get<PositionOut[]>(`/nodes/${encodeURIComponent(id)}/positions?limit=${limit}`);
export const fetchNodeTelemetry = (id: string, limit = 50) =>
  get<TelemetryOut[]>(`/nodes/${encodeURIComponent(id)}/telemetry?limit=${limit}`);
export const fetchGateways = () => get<GatewayOut[]>("/gateways");

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

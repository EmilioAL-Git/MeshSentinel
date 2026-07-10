import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import type {
  AlertOut,
  BatchDetailOut,
  DashboardSummaryOut,
  EventsSocketStatus,
  GatewayOut,
  OperationOut,
} from "../../api/client";
import { usePersistedState } from "../../hooks/usePersistedState";
import { t } from "../../tokens";

/**
 * Barra inferior de estado (v0.7 §11.2): 28 px, visible en TODAS las vistas.
 * Es el hilo conductor que hace autosuficiente cualquier ventana/monitor.
 * La caída del WebSocket es estado de primera clase: segmento en ámbar y
 * "datos congelados desde HH:MM:SS" (antes la UI se congelaba en silencio).
 */

const barStyle: CSSProperties = {
  flexShrink: 0,
  height: "var(--statusbar-height)",
  display: "flex",
  alignItems: "center",
  gap: 0,
  background: t.surface,
  borderTop: `1px solid ${t.border}`,
  fontFamily: t.fontMono,
  fontSize: 11.5,
  fontVariantNumeric: "tabular-nums",
  color: t.textDim,
  padding: "0 0.75rem",
  zIndex: 900,
  whiteSpace: "nowrap",
  overflow: "hidden",
};

function Segment({
  children,
  title,
  onClick,
}: {
  children: ReactNode;
  title?: string;
  onClick?: () => void;
}) {
  return (
    <button
      title={title}
      onClick={onClick}
      style={{
        background: "none",
        border: "none",
        borderRight: `1px solid ${t.borderSubtle}`,
        color: "inherit",
        font: "inherit",
        padding: "0 0.7rem",
        height: "100%",
        cursor: onClick ? "pointer" : "default",
        display: "inline-flex",
        alignItems: "center",
        gap: "0.35rem",
      }}
    >
      {children}
    </button>
  );
}

function hhmmss(d: Date): string {
  return d.toLocaleTimeString("es-ES", { hour12: false });
}

export function StatusBar({
  wsStatus,
  backendOk,
  summary,
  gateways,
  alerts,
  operations,
  runningBatch,
  onGoTo,
}: {
  wsStatus: EventsSocketStatus;
  backendOk: boolean;
  summary: DashboardSummaryOut | undefined;
  gateways: GatewayOut[];
  alerts: AlertOut[];
  operations: OperationOut[];
  runningBatch: BatchDetailOut | undefined;
  onGoTo: (view: "nodes" | "gateways" | "alerts" | "operations" | "batches") => void;
}) {
  const [utc, setUtc] = usePersistedState<boolean>("statusbar.utc", true);
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 10_000);
    return () => window.clearInterval(timer);
  }, []);

  const enabled = gateways.filter((g) => g.enabled && g.deleted_at == null);
  const connected = enabled.filter((g) => g.status === "connected").length;
  const gwProblem = connected < enabled.length;

  const active = alerts.filter((a) => a.status !== "resolved");
  const hasCrit = active.some((a) => a.severity === "CRITICAL");
  const alertColor = active.length === 0 ? t.textDim : hasCrit ? t.crit : t.warn;

  const queuedCount = operations.filter((o) => o.status === "pending" || o.status === "queued").length;
  const runningCount = operations.filter((o) => o.status === "running").length;

  // Conexión: el backend caído manda sobre el estado del WS
  const conn = !backendOk
    ? { color: t.crit, label: "Backend inaccesible", pulse: false }
    : wsStatus.state === "connected"
      ? { color: t.ok, label: "Conectado", pulse: true }
      : wsStatus.state === "connecting"
        ? { color: t.warn, label: "Conectando…", pulse: false }
        : {
            color: t.warn,
            label: `Reconectando — datos congelados desde ${
              wsStatus.disconnectedAt ? hhmmss(wsStatus.disconnectedAt) : "…"
            }`,
            pulse: false,
          };

  const clock = utc
    ? `${String(now.getUTCHours()).padStart(2, "0")}:${String(now.getUTCMinutes()).padStart(2, "0")} UTC`
    : `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")} local`;

  return (
    <footer style={barStyle}>
      <Segment title="Estado de la conexión en tiempo real (WebSocket + backend)">
        <span className={conn.pulse ? "noc-pulse" : undefined} style={{ color: conn.color }}>
          ●
        </span>
        <span style={{ color: conn.color === t.ok ? "inherit" : conn.color }}>{conn.label}</span>
      </Segment>
      <Segment title="Pasarelas conectadas / habilitadas" onClick={() => onGoTo("gateways")}>
        <span style={{ color: gwProblem ? t.crit : "inherit" }}>
          ⛭ GW {connected}/{enabled.length}
        </span>
      </Segment>
      <Segment title="Alertas activas" onClick={() => onGoTo("alerts")}>
        <span style={{ color: alertColor }}>⚠ {active.length}</span>
      </Segment>
      <Segment title="Operaciones en cola (pendientes + encoladas)" onClick={() => onGoTo("operations")}>
        ⧗ {queuedCount}
      </Segment>
      <Segment
        title="Operaciones ejecutándose y lote activo"
        onClick={() => onGoTo(runningBatch ? "batches" : "operations")}
      >
        ▶ {runningCount} op
        {runningBatch && (
          <span style={{ color: t.accent }}>
            · #{runningBatch.id} {Math.round(runningBatch.progress.percent)}%
          </span>
        )}
      </Segment>
      <Segment title="Nodos online / total (sin ignorados)" onClick={() => onGoTo("nodes")}>
        {summary ? `${summary.nodes_online}/${summary.nodes_total} ⬆` : "…"}
      </Segment>
      <span style={{ marginLeft: "auto" }} />
      <Segment title="Cambiar entre hora UTC y local" onClick={() => setUtc(!utc)}>
        {clock}
      </Segment>
    </footer>
  );
}

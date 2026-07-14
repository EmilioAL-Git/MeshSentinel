import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import type {
  AlertCountsOut,
  BatchDetailOut,
  DashboardSummaryOut,
  EventsSocketStatus,
  GatewayOut,
  OperationCountsOut,
} from "../../api/client";
import { useAuth } from "../../context/AuthContext";
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
  alertCounts,
  operationCounts,
  runningBatch,
  onGoTo,
}: {
  wsStatus: EventsSocketStatus;
  backendOk: boolean;
  summary: DashboardSummaryOut | undefined;
  gateways: GatewayOut[];
  /** Agregados reales del backend (hardening) — nunca listas truncadas. */
  alertCounts: AlertCountsOut | undefined;
  operationCounts: OperationCountsOut | undefined;
  runningBatch: BatchDetailOut | undefined;
  onGoTo: (view: "nodes" | "gateways" | "alerts" | "jobs") => void;
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

  const activeAlerts = alertCounts?.active ?? 0;
  const hasCrit = (alertCounts?.critical_active ?? 0) > 0;
  const alertColor = activeAlerts === 0 ? t.textDim : hasCrit ? t.crit : t.warn;

  const queuedCount = (operationCounts?.pending ?? 0) + (operationCounts?.queued ?? 0);
  const runningCount = operationCounts?.running ?? 0;

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
        <span style={{ color: alertColor }}>⚠ {activeAlerts}</span>
      </Segment>
      <Segment title="Operaciones en cola (pendientes + encoladas)" onClick={() => onGoTo("jobs")}>
        ⧗ {queuedCount}
      </Segment>
      <Segment
        title="Operaciones ejecutándose y lote activo"
        onClick={() => onGoTo("jobs")}
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
      <SessionSegment />
      <Segment title="Cambiar entre hora UTC y local" onClick={() => setUtc(!utc)}>
        {clock}
      </Segment>
    </footer>
  );
}

/** Sesión (autenticación): "Iniciar sesión" abre el modal; autenticado
 * muestra el nombre y cierra sesión al click — sin submenú, coherente con
 * el resto de segmentos (una acción por click). En modo abierto (sin
 * ningún admin todavía) sigue mostrando "Iniciar sesión" por si alguien
 * quiere crear el primer usuario. */
function SessionSegment() {
  const { isAuthenticated, me, openLoginModal, doLogout } = useAuth();
  if (isAuthenticated && me?.user) {
    return (
      <Segment title="Cerrar sesión" onClick={() => void doLogout()}>
        👤 {me.user.display_name}
      </Segment>
    );
  }
  return (
    <Segment title="Iniciar sesión" onClick={openLoginModal}>
      Iniciar sesión
    </Segment>
  );
}

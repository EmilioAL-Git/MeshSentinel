import type L from "leaflet";
import type { ActivityEntry } from "../../activity";
import type {
  AlertOut,
  BatchDetailOut,
  DashboardSummaryOut,
  GatewayOut,
  MultiGatewayStatsOut,
  NodeSummaryOut,
  OperationOut,
} from "../../api/client";
import { usePersistedState } from "../../hooks/usePersistedState";
import { t } from "../../tokens";
import { MapView } from "../MapView";
import { ActivityPanel } from "./ActivityPanel";
import { ConsoleRail } from "./ConsoleRail";
import { JobsPanel } from "./JobsPanel";
import { StatusPanel } from "./StatusPanel";

/**
 * Centro de Operaciones (v0.7 §3): la pantalla principal de MeshSentinel.
 * Tres columnas — estado (leer) · mapa (lienzo protagonista) · consola
 * operativa (actuar) — el operador trabaja aquí sin cambiar de pantalla.
 * El detalle de nodo es el Inspector GLOBAL (renderizado en App, §8.1):
 * este componente solo selecciona; el cajón es el mismo en toda la app.
 */

const collapseBtn = (side: "left" | "right"): React.CSSProperties => ({
  position: "absolute",
  top: "50%",
  [side === "left" ? "right" : "left"]: -1,
  transform: "translateY(-50%)",
  zIndex: 810,
  width: 14,
  height: 44,
  background: t.surface,
  border: `1px solid ${t.border}`,
  borderRadius: side === "left" ? "0 4px 4px 0" : "4px 0 0 4px",
  color: t.textDim,
  cursor: "pointer",
  fontSize: 9,
  padding: 0,
});

export function OpsCenter({
  summaries,
  gatewayNodeIds,
  summary,
  alerts,
  gateways,
  stats,
  operations,
  runningBatch,
  activity,
  selected,
  onSelect,
  onGoTo,
  onMapReady,
}: {
  summaries: NodeSummaryOut[];
  gatewayNodeIds: Set<string>;
  summary: DashboardSummaryOut | undefined;
  alerts: AlertOut[];
  gateways: GatewayOut[];
  stats: MultiGatewayStatsOut | undefined;
  operations: OperationOut[];
  runningBatch: BatchDetailOut | undefined;
  activity: ActivityEntry[];
  selected: string | null;
  onSelect: (nodeId: string | null) => void;
  onGoTo: (view: string) => void;
  onMapReady: (map: L.Map) => void;
}) {
  const [leftOpen, setLeftOpen] = usePersistedState<boolean>("ops.left.open", true);
  const setSelected = onSelect;

  const activeOps = operations.filter(
    (o) => o.status === "pending" || o.status === "queued" || o.status === "running",
  ).length;
  const activeAlerts = alerts.filter((a) => a.status !== "resolved");

  return (
    <div style={{ display: "flex", height: "100%", minHeight: 0, position: "relative" }}>
      {/* Panel izquierdo: estado (leer) */}
      <div
        style={{
          width: leftOpen ? 300 : 0,
          flexShrink: 0,
          background: t.surface,
          borderRight: leftOpen ? `1px solid ${t.border}` : "none",
          overflow: "hidden",
          transition: "width 180ms ease-out",
          position: "relative",
        }}
      >
        {leftOpen && (
          <StatusPanel
            summary={summary}
            alerts={alerts}
            gateways={gateways}
            stats={stats}
            onOpenNode={setSelected}
            onGoTo={onGoTo}
          />
        )}
      </div>

      {/* Mapa: lienzo protagonista, borde a borde. Clic en marcador = abrir
          el Inspector global (renderizado en App, §8.1) */}
      <div style={{ flex: 1, minWidth: 0, position: "relative" }}>
        <MapView
          summaries={summaries}
          gatewayNodeIds={gatewayNodeIds}
          onShowDetail={setSelected}
          fill
          selectedId={selected}
          onMapReady={onMapReady}
        />
        <button
          style={collapseBtn("left")}
          onClick={() => setLeftOpen(!leftOpen)}
          title={leftOpen ? "Plegar panel de estado" : "Desplegar panel de estado"}
        >
          {leftOpen ? "◂" : "▸"}
        </button>
      </div>

      {/* Consola operativa: riel de iconos (actuar) */}
      <ConsoleRail
        width={360}
        panels={[
          {
            id: "activity",
            icon: "▤",
            title: "Actividad — qué está ocurriendo ahora",
            content: <ActivityPanel entries={activity} onOpenNode={setSelected} />,
          },
          {
            id: "jobs",
            icon: "▶",
            title: "Trabajos — operaciones y lotes",
            badge: activeOps,
            content: (
              <JobsPanel
                operations={operations}
                summaries={summaries}
                runningBatch={runningBatch}
                onGoTo={onGoTo}
              />
            ),
          },
          {
            id: "alerts",
            icon: "⚠",
            title: "Alertas activas",
            badge: activeAlerts.length,
            badgeColor: activeAlerts.some((a) => a.severity === "CRITICAL") ? t.crit : t.warn,
            content: (
              <div style={{ padding: "0.5rem 0.75rem", overflowY: "auto", height: "100%" }}>
                <span style={{ color: t.textDim, fontSize: 11, letterSpacing: "0.08em", fontWeight: 600 }}>
                  ALERTAS
                </span>
                {activeAlerts.length === 0 && (
                  <p style={{ color: t.textFaint, fontSize: 12 }}>Sin alertas activas.</p>
                )}
                {activeAlerts.map((a) => (
                  <div key={a.id} style={{ fontSize: 12, padding: "0.25rem 0", borderBottom: `1px solid ${t.borderSubtle}` }}>
                    <span style={{ color: a.severity === "CRITICAL" ? t.crit : a.severity === "WARNING" ? t.warn : t.textDim }}>
                      ● {a.severity}
                    </span>{" "}
                    <span style={{ color: t.text }}>{a.message}</span>
                    {a.subject_type === "node" && (
                      <button
                        onClick={() => setSelected(a.subject_id)}
                        style={{
                          background: "none",
                          border: "none",
                          color: t.accent,
                          cursor: "pointer",
                          fontSize: 12,
                          padding: "0 0.3rem",
                        }}
                      >
                        →
                      </button>
                    )}
                  </div>
                ))}
              </div>
            ),
          },
        ]}
      />
    </div>
  );
}

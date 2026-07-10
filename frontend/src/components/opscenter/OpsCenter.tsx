import type L from "leaflet";
import { useEffect, useMemo, useRef, useState } from "react";
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
import { MapView, type MapPulse } from "../MapView";
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
  focusId,
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
  focusId: string | null;
  onSelect: (nodeId: string | null) => void;
  onGoTo: (view: string) => void;
  onMapReady: (map: L.Map) => void;
}) {
  const [leftOpen, setLeftOpen] = usePersistedState<boolean>("ops.left.open", true);
  const setSelected = onSelect;

  // ── Mapa vivo (v0.7.3): un pulso de una sola vez por evento nuevo ──────────
  // El feed de actividad ya llega deduplicado y en lotes de 1 s; aquí solo se
  // detectan las entradas no vistas y se convierten en pulsos efímeros (1.4 s)
  // sobre la posición del nodo. Nada de esto re-renderiza los marcadores.
  const positionOf = useMemo(() => {
    const map = new Map<string, [number, number]>();
    for (const s of summaries) {
      if (s.last_position) map.set(s.node.node_id, [s.last_position.latitude, s.last_position.longitude]);
    }
    return map;
  }, [summaries]);
  const [pulses, setPulses] = useState<MapPulse[]>([]);
  const seenEntries = useRef<Set<string>>(new Set());
  useEffect(() => {
    const fresh: MapPulse[] = [];
    for (const e of activity.slice(0, 12)) {
      if (seenEntries.current.has(e.id)) continue;
      seenEntries.current.add(e.id);
      if (!e.nodeId) continue;
      const pos = positionOf.get(e.nodeId);
      if (!pos) continue;
      const color =
        e.category === "alerta"
          ? t.crit
          : e.severity === "ok"
            ? t.ok
            : e.severity === "warn" || e.severity === "error"
              ? t.warn
              : t.accent;
      fresh.push({ key: e.id, lat: pos[0], lng: pos[1], color });
    }
    if (seenEntries.current.size > 2000) seenEntries.current.clear();
    if (fresh.length === 0) return;
    const batch = fresh.slice(0, 8); // límite anti-tormenta
    setPulses((prev) => [...prev, ...batch].slice(-20));
    const timer = window.setTimeout(() => {
      setPulses((prev) => prev.filter((p) => !batch.some((b) => b.key === p.key)));
    }, 1_500);
    return () => window.clearTimeout(timer);
  }, [activity, positionOf]);

  // Nodos con alerta CRITICAL activa: halo permanente, jamás atenuados
  const alertNodeIds = useMemo(
    () =>
      new Set(
        alerts
          .filter((a) => a.status !== "resolved" && a.severity === "CRITICAL" && a.subject_type === "node")
          .map((a) => a.subject_id),
      ),
    [alerts],
  );

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
            focusId={focusId}
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
          focusId={focusId}
          alertNodeIds={alertNodeIds}
          pulses={pulses}
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
            content: (
              <ActivityPanel
                entries={activity}
                focusId={focusId}
                focusLabel={
                  focusId
                    ? (summaries.find((s) => s.node.node_id === focusId)?.node.short_name ?? focusId)
                    : null
                }
                selectedId={selected}
                onOpenNode={setSelected}
              />
            ),
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
                focusId={focusId}
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

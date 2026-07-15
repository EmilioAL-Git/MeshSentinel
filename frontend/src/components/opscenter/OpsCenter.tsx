import type L from "leaflet";
import { useQuery } from "@tanstack/react-query";
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
import { fetchTopology } from "../../api/client";
import { useGroupNodeIds } from "../../context/GroupContext";
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

// Se renderiza dentro del contenedor del MAPA (no del panel que colapsa), en
// el borde que linda con ese panel: "left" = pegado al borde IZQUIERDO del
// mapa (linda con StatusPanel), "right" = pegado al borde DERECHO (linda con
// ConsoleRail). Antes usaba `right:-1` para "left", lo que lo pegaba al lado
// contrario (junto al riel derecho) — bug reportado por el usuario.
const collapseBtn = (side: "left" | "right"): React.CSSProperties => ({
  position: "absolute",
  top: "50%",
  [side]: -1,
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
  // Plegado del riel derecho (ConsoleRail): antes solo se podía plegar
  // clicando el icono activo dentro del propio riel; controlado aquí para
  // poder ofrecer también la flecha de borde, simétrica a la del panel
  // izquierdo.
  const [railOpen, setRailOpen] = usePersistedState<boolean>("rail.open", true);
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

  // Flujo de tráfico entre nodos (§8): reutiliza la topología real
  // (node_neighbors, motor-de-reglas-y-topologia.md §2) para que un evento
  // de un nodo con vecinos conocidos pulse también sobre el punto medio de
  // cada enlace, dando sensación de flujo en vez de un punto aislado.
  const { data: topologyLinks } = useQuery({
    queryKey: ["topology"],
    queryFn: () => fetchTopology(),
    refetchInterval: 20_000,
  });
  const neighborMidpointsOf = useMemo(() => {
    const map = new Map<string, [number, number][]>();
    for (const link of topologyLinks ?? []) {
      if (!link.active) continue;
      const a = positionOf.get(link.node_id);
      const b = positionOf.get(link.neighbor_id);
      if (!a || !b) continue;
      const mid: [number, number] = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      const list = map.get(link.node_id) ?? [];
      list.push(mid);
      map.set(link.node_id, list);
    }
    return map;
  }, [topologyLinks, positionOf]);

  // Nombre COMPLETO por nodo para las tarjetas de actividad (la entrada del
  // backend solo trae el nombre corto).
  const nodeNames = useMemo(() => {
    const map = new Map<string, string>();
    for (const s of summaries) {
      const name = s.node.long_name ?? s.node.short_name;
      if (name) map.set(s.node.node_id, name);
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
      // Registro persistente (hardening): las entradas sembradas del
      // histórico no son tráfico de ahora — sin pulso para lo antiguo.
      if (Date.now() - e.receivedAtMs > 120_000) continue;
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
      // Punto medio de cada enlace real conocido de este nodo (tope 2 por
      // evento, el límite general de lote de abajo sigue aplicando).
      const midpoints = neighborMidpointsOf.get(e.nodeId) ?? [];
      for (const [i, mid] of midpoints.slice(0, 2).entries()) {
        fresh.push({ key: `${e.id}-edge-${i}`, lat: mid[0], lng: mid[1], color });
      }
    }
    if (seenEntries.current.size > 2000) seenEntries.current.clear();
    if (fresh.length === 0) return;
    const batch = fresh.slice(0, 8); // límite anti-tormenta
    setPulses((prev) => [...prev, ...batch].slice(-20));
    const timer = window.setTimeout(() => {
      setPulses((prev) => prev.filter((p) => !batch.some((b) => b.key === p.key)));
    }, 1_500);
    return () => window.clearTimeout(timer);
  }, [activity, positionOf, neighborMidpointsOf]);

  // Grupo activo: nodos fuera de él se atenúan en el mapa, nunca se ocultan.
  const groupNodeIds = useGroupNodeIds(summaries);

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

  return (
    <div style={{ display: "flex", height: "100%", minHeight: 0, position: "relative" }}>
      {/* Panel izquierdo: estado (leer) */}
      <div
        style={{
          width: leftOpen ? 340 : 0,
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
            summaries={summaries}
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
          gateways={gateways}
          onShowDetail={setSelected}
          fill
          selectedId={selected}
          focusId={focusId}
          alertNodeIds={alertNodeIds}
          groupNodeIds={groupNodeIds}
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
        <button
          style={collapseBtn("right")}
          onClick={() => setRailOpen(!railOpen)}
          title={railOpen ? "Plegar consola" : "Desplegar consola"}
        >
          {railOpen ? "▸" : "◂"}
        </button>
      </div>

      {/* Consola operativa: riel de iconos (actuar) */}
      <ConsoleRail
        width={360}
        open={railOpen}
        onToggleOpen={setRailOpen}
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
                nodeNames={nodeNames}
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
          // El panel "Alertas" del riel se eliminó (consolidación del
          // Centro): una ÚNICA lista de alertas por pantalla — vive en la
          // cola de ATENCIÓN del StatusPanel, con ACK inline.
        ]}
      />
    </div>
  );
}

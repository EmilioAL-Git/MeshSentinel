import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ACTIVITY_LIMIT, toEntry, type ActivityEntry } from "./activity";
import {
  fetchAlerts,
  fetchDashboardSummary,
  fetchGateways,
  fetchHealth,
  fetchNodes,
  openEventsSocket,
} from "./api/client";
import { AlertsView } from "./components/AlertsView";
import { Dashboard } from "./components/Dashboard";
import { OperationsView } from "./components/OperationsView";
import { MapView } from "./components/MapView";
import { NodeDetail } from "./components/NodeDetail";
import { NodesTable } from "./components/NodesTable";
import { styles } from "./styles";

const DATA_EVENTS = new Set([
  "node.seen",
  "position.updated",
  "telemetry.received",
  "gateway.status",
  "alert.fired",
  "alert.resolved",
  "admin.operation",
]);

type View = "dashboard" | "nodes" | "map" | "alerts" | "operations";

function NavTab({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: active ? "#1f6feb" : "transparent",
        color: "#e6edf3",
        border: "1px solid " + (active ? "#1f6feb" : "#30363d"),
        borderRadius: 6,
        padding: "0.35rem 1rem",
        cursor: "pointer",
        fontSize: "0.9rem",
      }}
    >
      {label}
    </button>
  );
}

export default function App() {
  const queryClient = useQueryClient();
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth, refetchInterval: 15_000 });
  const nodes = useQuery({ queryKey: ["nodes"], queryFn: fetchNodes, refetchInterval: 30_000 });
  const gateways = useQuery({ queryKey: ["gateways"], queryFn: fetchGateways, refetchInterval: 30_000 });
  const dashboard = useQuery({
    queryKey: ["dashboard"],
    queryFn: fetchDashboardSummary,
    refetchInterval: 30_000,
  });
  const alerts = useQuery({
    queryKey: ["alerts"],
    queryFn: () => fetchAlerts(undefined, 100),
    refetchInterval: 30_000,
  });
  const [view, setView] = useState<View>("dashboard");
  const [selected, setSelected] = useState<string | null>(null);
  const [activity, setActivity] = useState<ActivityEntry[]>([]);
  const invalidateTimer = useRef<number | null>(null);

  // Resolución de nombres para el feed sin recrear la conexión WS
  const nodeNamesRef = useRef<Map<string, string>>(new Map());
  useEffect(() => {
    const map = new Map<string, string>();
    for (const s of nodes.data ?? []) {
      map.set(s.node.node_id, s.node.short_name ?? s.node.node_id);
    }
    nodeNamesRef.current = map;
  }, [nodes.data]);

  useEffect(() => {
    // Tormentas de eventos controladas en dos niveles:
    // 1) las queries se invalidan agrupadas en ventanas de 2s;
    // 2) el feed de actividad se acumula en un ref y se vuelca al estado
    //    como máximo 1 vez por segundo (cero peticiones HTTP).
    const pending: ActivityEntry[] = [];
    const nodeName = (id: string) => nodeNamesRef.current.get(id) ?? id;

    const ws = openEventsSocket((event) => {
      if (!DATA_EVENTS.has(event.event_type)) return;
      const entry = toEntry(event, nodeName);
      if (entry) pending.unshift(entry);

      if (invalidateTimer.current == null) {
        invalidateTimer.current = window.setTimeout(() => {
          invalidateTimer.current = null;
          queryClient.invalidateQueries({ queryKey: ["nodes"] });
          queryClient.invalidateQueries({ queryKey: ["gateways"] });
          queryClient.invalidateQueries({ queryKey: ["dashboard"] });
          queryClient.invalidateQueries({ queryKey: ["alerts"] });
          queryClient.invalidateQueries({ queryKey: ["operations"] });
        }, 2000);
      }
    });

    const flush = window.setInterval(() => {
      if (pending.length === 0) return;
      setActivity((prev) => {
        const merged = [...pending.splice(0), ...prev];
        // Dedupe de heartbeats consecutivos idénticos (p. ej. gateway.status cada 30s)
        const deduped = merged.filter((e, i) => i === 0 || e.text !== merged[i - 1].text);
        return deduped.slice(0, ACTIVITY_LIMIT);
      });
    }, 1000);

    return () => {
      ws.close();
      window.clearInterval(flush);
      if (invalidateTimer.current != null) window.clearTimeout(invalidateTimer.current);
    };
  }, [queryClient]);

  const summaries = nodes.data ?? [];
  const onlineCount = summaries.filter((s) => s.node.online).length;
  const activeAlertCount = (alerts.data ?? []).filter((a) => a.status !== "resolved").length;

  const gatewayNodeIds = useMemo(
    () =>
      new Set(
        (gateways.data ?? [])
          .map((g) => g.local_node_id)
          .filter((id): id is string => id != null),
      ),
    [gateways.data],
  );

  const showDetail = useCallback((nodeId: string) => {
    setSelected(nodeId);
    setView("nodes");
  }, []);

  return (
    <div style={styles.page}>
      <div style={{ display: "flex", alignItems: "center", gap: "1.5rem", marginBottom: "1rem" }}>
        <h1 style={{ margin: 0 }}>Meshtastic NOC</h1>
        <nav style={{ display: "flex", gap: "0.5rem" }}>
          <NavTab active={view === "dashboard"} label="Dashboard" onClick={() => setView("dashboard")} />
          <NavTab active={view === "nodes"} label="Nodos" onClick={() => setView("nodes")} />
          <NavTab active={view === "map"} label="Mapa" onClick={() => setView("map")} />
          <NavTab
            active={view === "alerts"}
            label={activeAlertCount > 0 ? `Alertas (${activeAlertCount})` : "Alertas"}
            onClick={() => setView("alerts")}
          />
          <NavTab active={view === "operations"} label="Operaciones" onClick={() => setView("operations")} />
        </nav>
        <span style={{ marginLeft: "auto" }}>
          Backend:{" "}
          {health.isError ? (
            <span style={styles.bad}>inaccesible</span>
          ) : (
            <span style={health.data?.status === "ok" ? styles.ok : styles.bad}>
              {health.data?.status ?? "…"}
            </span>
          )}
        </span>
      </div>

      {view === "dashboard" && (
        <Dashboard
          summary={dashboard.data}
          loading={dashboard.isLoading}
          activity={activity}
          onNavigate={setView}
          onShowDetail={showDetail}
        />
      )}

      {view === "alerts" && <AlertsView />}

      {view === "operations" && <OperationsView summaries={summaries} />}

      {view === "map" && (
        <MapView summaries={summaries} gatewayNodeIds={gatewayNodeIds} onShowDetail={showDetail} />
      )}

      {view === "nodes" && (
        <div style={selected ? styles.layout : undefined}>
          <div style={styles.card}>
            <h2 style={{ marginTop: 0 }}>
              Nodos descubiertos <span style={styles.dim}>({onlineCount} online)</span>
            </h2>
            {nodes.isLoading && <p>Cargando…</p>}
            {nodes.isError && <p style={styles.bad}>Error consultando la API</p>}
            {summaries.length === 0 && !nodes.isLoading && (
              <p style={styles.dim}>Aún no se ha descubierto ningún nodo. Esperando eventos de la pasarela…</p>
            )}
            {summaries.length > 0 && (
              <NodesTable summaries={summaries} selected={selected} onSelect={setSelected} />
            )}
          </div>
          {selected && <NodeDetail nodeId={selected} onClose={() => setSelected(null)} />}
        </div>
      )}
    </div>
  );
}

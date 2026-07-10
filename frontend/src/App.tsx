import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ACTIVITY_LIMIT, DASHBOARD_ACTIVITY_LIMIT, toEntry, type ActivityEntry } from "./activity";
import {
  fetchAlerts,
  fetchBatch,
  fetchBatches,
  fetchDashboardSummary,
  fetchGateways,
  fetchGroups,
  fetchHealth,
  fetchNodes,
  fetchOperations,
  fetchProfiles,
  fetchTags,
  openEventsSocket,
  setNodeFavorite,
  setNodeIgnored,
  type EventsSocketStatus,
  type NodeFilterParams,
} from "./api/client";
import { ActivityConsole } from "./components/ActivityConsole";
import { AlertsView } from "./components/AlertsView";
import { BatchesView, BatchWizard } from "./components/BatchesView";
import { ConfigEditor } from "./components/ConfigEditor";
import { Dashboard } from "./components/Dashboard";
import { GatewaysView } from "./components/GatewaysView";
import { MapView } from "./components/MapView";
import { NodeDetail } from "./components/NodeDetail";
import { NodeFiltersBar } from "./components/NodeFiltersBar";
import { NodesTable } from "./components/NodesTable";
import { OperationsView } from "./components/OperationsView";
import { ProfilesView } from "./components/ProfilesView";
import { CommandPalette } from "./components/shell/CommandPalette";
import { Hud } from "./components/shell/Hud";
import { StatusBar } from "./components/shell/StatusBar";
import { styles } from "./styles";
import { t } from "./tokens";

const DATA_EVENTS = new Set([
  "node.seen",
  "position.updated",
  "telemetry.received",
  "gateway.status",
  "alert.fired",
  "alert.resolved",
  "admin.operation",
  "admin.batch",
]);

type View =
  | "dashboard"
  | "nodes"
  | "map"
  | "alerts"
  | "operations"
  | "config"
  | "profiles"
  | "batches"
  | "activity"
  | "gateways";

// Vistas de la aplicación: alimenta la navegación y las acciones "Ir a" de ⌘K
const VIEWS: { id: View; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "nodes", label: "Nodos" },
  { id: "map", label: "Mapa" },
  { id: "alerts", label: "Alertas" },
  { id: "operations", label: "Operaciones" },
  { id: "config", label: "Configuración" },
  { id: "profiles", label: "Perfiles" },
  { id: "batches", label: "Batches" },
  { id: "activity", label: "Actividad" },
  { id: "gateways", label: "Gateways" },
];

const selBtn = {
  background: "transparent",
  color: "var(--text)",
  border: "1px solid var(--border)",
  borderRadius: 6,
  padding: "0.2rem 0.7rem",
  cursor: "pointer",
  fontSize: "0.85rem",
} as const;

function NavTab({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: active ? "var(--accent)" : "transparent",
        color: "var(--text)",
        border: "1px solid " + (active ? "var(--accent)" : "var(--border)"),
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
  // Query base (sin ignorados): la usan Mapa, Dashboard, Operaciones y el feed
  const nodes = useQuery({ queryKey: ["nodes"], queryFn: () => fetchNodes(), refetchInterval: 30_000 });
  const [filters, setFilters] = useState<NodeFilterParams>({});
  // Query filtrada para la vista Nodos (búsqueda avanzada M1.2)
  const filteredNodes = useQuery({
    queryKey: ["nodes", filters],
    queryFn: () => fetchNodes(filters),
    refetchInterval: 30_000,
  });
  const tags = useQuery({ queryKey: ["tags"], queryFn: fetchTags });
  const groups = useQuery({ queryKey: ["groups"], queryFn: fetchGroups });
  const gateways = useQuery({ queryKey: ["gateways"], queryFn: () => fetchGateways(), refetchInterval: 30_000 });
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
  // Soporte del shell v0.7 (HUD + barra inferior): cola/actividad admin y lote
  // en curso. Las claves coinciden con las que ya invalida el handler del WS.
  const operations = useQuery({
    queryKey: ["operations", "shell"],
    queryFn: () => fetchOperations(undefined, 200),
    refetchInterval: 30_000,
  });
  const runningBatches = useQuery({
    queryKey: ["batches", "running"],
    queryFn: () => fetchBatches({ status: "running", limit: 5 }),
    refetchInterval: 30_000,
  });
  const runningBatchId = runningBatches.data?.[0]?.id;
  const runningBatch = useQuery({
    queryKey: ["batch", runningBatchId],
    queryFn: () => fetchBatch(runningBatchId!),
    enabled: runningBatchId != null,
    refetchInterval: 10_000,
  });
  const [view, setView] = useState<View>("dashboard");
  const [wsStatus, setWsStatus] = useState<EventsSocketStatus>({
    state: "connecting",
    disconnectedAt: null,
  });
  const [paletteOpen, setPaletteOpen] = useState(false);
  // Perfiles: solo se cargan cuando la paleta los necesita
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: fetchProfiles, enabled: paletteOpen });
  const [selected, setSelected] = useState<string | null>(null);
  // Selección múltiple para batches (M2)
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  const [wizardOpen, setWizardOpen] = useState(false);
  const [openBatchId, setOpenBatchId] = useState<number | null>(null);
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
    // gateway.status llega como heartbeat cada 30 s: solo interesa el CAMBIO
    // de estado (conexión/desconexión/reconexión), no cada latido
    const lastGatewayStatus = new Map<string, string>();

    const ws = openEventsSocket((event) => {
      if (!DATA_EVENTS.has(event.event_type)) return;
      let skipEntry = false;
      if (event.event_type === "gateway.status") {
        const status = String(event.payload.status ?? "");
        skipEntry = lastGatewayStatus.get(event.gateway_id) === status;
        lastGatewayStatus.set(event.gateway_id, status);
      }
      const entry = skipEntry ? null : toEntry(event, nodeName);
      if (entry) pending.unshift(entry);

      if (invalidateTimer.current == null) {
        invalidateTimer.current = window.setTimeout(() => {
          invalidateTimer.current = null;
          queryClient.invalidateQueries({ queryKey: ["nodes"] });
          queryClient.invalidateQueries({ queryKey: ["gateways"] });
          queryClient.invalidateQueries({ queryKey: ["dashboard"] });
          queryClient.invalidateQueries({ queryKey: ["alerts"] });
          queryClient.invalidateQueries({ queryKey: ["operations"] });
          queryClient.invalidateQueries({ queryKey: ["batches"] });
          queryClient.invalidateQueries({ queryKey: ["batch"] });
          queryClient.invalidateQueries({ queryKey: ["batch-ops"] });
        }, 2000);
      }
    }, setWsStatus);

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

  // Al recuperar el WS tras una caída, todo puede estar obsoleto: refresco único
  const prevWsState = useRef(wsStatus.state);
  useEffect(() => {
    if (prevWsState.current === "reconnecting" && wsStatus.state === "connected") {
      queryClient.invalidateQueries();
    }
    prevWsState.current = wsStatus.state;
  }, [wsStatus.state, queryClient]);

  // Búsqueda global: Ctrl+K / ⌘K en cualquier vista (v0.7 §10)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const summaries = nodes.data ?? [];
  const filteredSummaries = filteredNodes.data ?? [];
  const onlineCount = filteredSummaries.filter((s) => s.node.online).length;
  const activeAlertCount = (alerts.data ?? []).filter((a) => a.status !== "resolved").length;
  const favorites = summaries.filter((s) => s.node.is_favorite);
  const hwModels = useMemo(
    () => [...new Set(summaries.map((s) => s.node.hw_model).filter((h): h is string => h != null))].sort(),
    [summaries],
  );

  const invalidateNodeData = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["nodes"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  }, [queryClient]);
  const toggleFavorite = useMutation({
    mutationFn: ({ id, value }: { id: string; value: boolean }) => setNodeFavorite(id, value),
    onSettled: invalidateNodeData,
  });
  const toggleIgnored = useMutation({
    mutationFn: ({ id, value }: { id: string; value: boolean }) => setNodeIgnored(id, value),
    onSettled: invalidateNodeData,
  });

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

  const selectedSummary =
    filteredSummaries.find((s) => s.node.node_id === selected) ??
    summaries.find((s) => s.node.node_id === selected);

  const activeOps = (operations.data ?? []).filter(
    (o) => o.status === "pending" || o.status === "queued" || o.status === "running",
  ).length;

  return (
    <div style={{ ...styles.page, paddingBottom: "calc(var(--statusbar-height) + 1.5rem)" }}>
      {/* Cabecera del shell v0.7 (§3.1): identidad + ⌘K + HUD. La fila de
          pestañas es transitoria hasta que el Centro llegue en v0.7.1. */}
      <div style={{ display: "flex", alignItems: "center", gap: "1.25rem", marginBottom: "0.75rem" }}>
        <h1 style={{ margin: 0, fontSize: "1.15rem", letterSpacing: "0.02em", whiteSpace: "nowrap" }}>
          ⌬ Meshtastic NOC
        </h1>
        <button
          onClick={() => setPaletteOpen(true)}
          title="Búsqueda global (Ctrl+K / ⌘K)"
          style={{
            background: t.bg,
            color: t.textDim,
            border: `1px solid ${t.border}`,
            borderRadius: 6,
            padding: "0.3rem 0.9rem",
            cursor: "pointer",
            fontSize: "0.85rem",
            display: "inline-flex",
            alignItems: "center",
            gap: "0.5rem",
            minWidth: 220,
          }}
        >
          <span>🔍 Buscar…</span>
          <span style={{ marginLeft: "auto", fontFamily: t.fontMono, fontSize: "0.75rem" }}>⌘K</span>
        </button>
        <span style={{ marginLeft: "auto" }} />
        <Hud
          summary={dashboard.data}
          gateways={gateways.data ?? []}
          alerts={alerts.data ?? []}
          activeOps={activeOps}
          onGoTo={setView}
        />
      </div>
      <nav style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "1rem" }}>
        <NavTab active={view === "dashboard"} label="Dashboard" onClick={() => setView("dashboard")} />
        <NavTab active={view === "nodes"} label="Nodos" onClick={() => setView("nodes")} />
        <NavTab active={view === "map"} label="Mapa" onClick={() => setView("map")} />
        <NavTab
          active={view === "alerts"}
          label={activeAlertCount > 0 ? `Alertas (${activeAlertCount})` : "Alertas"}
          onClick={() => setView("alerts")}
        />
        <NavTab active={view === "operations"} label="Operaciones" onClick={() => setView("operations")} />
        <NavTab active={view === "config"} label="Configuración" onClick={() => setView("config")} />
        <NavTab active={view === "profiles"} label="Perfiles" onClick={() => setView("profiles")} />
        <NavTab active={view === "batches"} label="Batches" onClick={() => setView("batches")} />
        <NavTab active={view === "activity"} label="Actividad" onClick={() => setView("activity")} />
        <NavTab active={view === "gateways"} label="Gateways" onClick={() => setView("gateways")} />
      </nav>

      {/* WS caído = estado de primera clase (§11.2): aviso fino, nunca silencio */}
      {wsStatus.state === "reconnecting" && (
        <div
          style={{
            background: t.warnTint,
            border: `1px solid ${t.warn}`,
            color: t.warn,
            borderRadius: 6,
            padding: "0.35rem 0.8rem",
            marginBottom: "0.75rem",
            fontSize: "0.85rem",
          }}
        >
          Reconectando con el servidor de eventos — datos congelados desde{" "}
          {wsStatus.disconnectedAt?.toLocaleTimeString("es-ES", { hour12: false }) ?? "…"}
        </div>
      )}

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        summaries={summaries}
        gateways={gateways.data ?? []}
        tags={tags.data ?? []}
        groups={groups.data ?? []}
        profiles={profiles.data ?? []}
        views={VIEWS}
        onNavigate={(v) => setView(v as View)}
        onOpenNode={showDetail}
        onFilterTag={(tagName) => {
          setFilters({ tag: tagName });
          setView("nodes");
        }}
        onFilterGroup={(groupId) => {
          setFilters({ group_id: groupId });
          setView("nodes");
        }}
      />

      {view === "dashboard" && (
        <Dashboard
          summary={dashboard.data}
          loading={dashboard.isLoading}
          activity={activity.slice(0, DASHBOARD_ACTIVITY_LIMIT)}
          favorites={favorites}
          onNavigate={setView}
          onShowDetail={showDetail}
        />
      )}

      {view === "activity" && (
        <ActivityConsole
          entries={activity}
          summaries={summaries}
          gateways={gateways.data ?? []}
          onClear={() => setActivity([])}
        />
      )}

      {view === "gateways" && <GatewaysView />}

      {view === "alerts" && <AlertsView />}

      {view === "operations" && <OperationsView summaries={summaries} />}

      {view === "config" && <ConfigEditor summaries={summaries} />}

      {view === "profiles" && (
        <ProfilesView
          summaries={summaries}
          onOpenBatch={(batchId) => {
            setOpenBatchId(batchId);
            setView("batches");
          }}
        />
      )}

      {view === "batches" && (
        <BatchesView summaries={summaries} openBatchId={openBatchId} onOpenBatch={setOpenBatchId} />
      )}

      {view === "map" && (
        <MapView summaries={summaries} gatewayNodeIds={gatewayNodeIds} onShowDetail={showDetail} />
      )}

      {view === "nodes" && (
        <div>
          {wizardOpen && (
            <BatchWizard
              selectedIds={[...checkedIds]}
              summaries={summaries}
              onDone={(batchId) => {
                setWizardOpen(false);
                if (batchId != null) {
                  setCheckedIds(new Set());
                  setOpenBatchId(batchId);
                  setView("batches");
                }
              }}
            />
          )}
          <div style={selected ? styles.layout : undefined}>
            <div style={styles.card}>
              <h2 style={{ marginTop: 0 }}>
                Nodos <span style={styles.dim}>({filteredSummaries.length} · {onlineCount} online)</span>
              </h2>
              <NodeFiltersBar
                filters={filters}
                onChange={setFilters}
                tags={tags.data ?? []}
                groups={groups.data ?? []}
                gateways={gateways.data ?? []}
                hwModels={hwModels}
              />
              {/* Barra de selección para batches (M2) */}
              <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap", marginBottom: "0.6rem" }}>
                <span>
                  Seleccionados: <strong>{checkedIds.size}</strong>
                </span>
                <button
                  style={selBtn}
                  onClick={() =>
                    setCheckedIds(new Set([...checkedIds, ...filteredSummaries.map((s) => s.node.node_id)]))
                  }
                >
                  + visibles
                </button>
                <button
                  style={selBtn}
                  onClick={() => {
                    const visible = filteredSummaries.map((s) => s.node.node_id);
                    const next = new Set(checkedIds);
                    for (const id of visible) {
                      if (next.has(id)) next.delete(id);
                      else next.add(id);
                    }
                    setCheckedIds(next);
                  }}
                >
                  Invertir
                </button>
                <button
                  style={selBtn}
                  onClick={() =>
                    setCheckedIds(
                      new Set([
                        ...checkedIds,
                        ...summaries.filter((s) => s.node.is_favorite).map((s) => s.node.node_id),
                      ]),
                    )
                  }
                >
                  + favoritos
                </button>
                <button style={selBtn} onClick={() => setCheckedIds(new Set())} disabled={checkedIds.size === 0}>
                  Limpiar
                </button>
                <button
                  style={{ ...selBtn, background: checkedIds.size > 0 ? "var(--accent)" : "transparent" }}
                  disabled={checkedIds.size === 0}
                  onClick={() => setWizardOpen(true)}
                >
                  Crear batch ({checkedIds.size})
                </button>
              </div>
              {filteredNodes.isLoading && <p>Cargando…</p>}
              {filteredNodes.isError && <p style={styles.bad}>Error consultando la API</p>}
              {filteredSummaries.length === 0 && !filteredNodes.isLoading && (
                <p style={styles.dim}>Ningún nodo coincide con los filtros actuales.</p>
              )}
              {filteredSummaries.length > 0 && (
                <NodesTable
                  summaries={filteredSummaries}
                  selected={selected}
                  onSelect={setSelected}
                  onToggleFavorite={(id, value) => toggleFavorite.mutate({ id, value })}
                  onToggleIgnored={(id, value) => toggleIgnored.mutate({ id, value })}
                  checkedIds={checkedIds}
                  onToggleChecked={(id) => {
                    const next = new Set(checkedIds);
                    if (next.has(id)) next.delete(id);
                    else next.add(id);
                    setCheckedIds(next);
                  }}
                  onToggleCheckAll={() => {
                    const visible = filteredSummaries.map((s) => s.node.node_id);
                    const allChecked = visible.every((id) => checkedIds.has(id));
                    const next = new Set(checkedIds);
                    for (const id of visible) {
                      if (allChecked) next.delete(id);
                      else next.add(id);
                    }
                    setCheckedIds(next);
                  }}
                />
              )}
            </div>
            {selected && (
              <NodeDetail
                nodeId={selected}
                summary={selectedSummary}
                summaries={summaries}
                onClose={() => setSelected(null)}
              />
            )}
          </div>
        </div>
      )}

      <StatusBar
        wsStatus={wsStatus}
        backendOk={!health.isError && health.data?.status === "ok"}
        summary={dashboard.data}
        gateways={gateways.data ?? []}
        alerts={alerts.data ?? []}
        operations={operations.data ?? []}
        runningBatch={runningBatch.data}
        onGoTo={setView}
      />
    </div>
  );
}

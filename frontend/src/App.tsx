import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ACTIVITY_LIMIT, toEntry, type ActivityEntry } from "./activity";
import {
  fetchActivityLog,
  fetchAlertCounts,
  fetchAlerts,
  fetchBatch,
  fetchBatches,
  fetchDashboardSummary,
  fetchGateways,
  fetchGatewayStats,
  fetchGroups,
  fetchHealth,
  fetchNodes,
  fetchOperationCounts,
  fetchOperations,
  fetchProfiles,
  fetchTags,
  openEventsSocket,
  setNodeFavorite,
  setNodeIgnored,
  type DashboardSummaryOut,
  type EventsSocketStatus,
  type NodeFilterParams,
} from "./api/client";
import { ActivityConsole } from "./components/ActivityConsole";
import { AlertsView } from "./components/AlertsView";
import { ChatConsole } from "./components/chat/ChatConsole";
import { ConfigEditor } from "./components/ConfigEditor";
import { FleetView } from "./components/fleet/FleetView";
import { GatewaysView } from "./components/GatewaysView";
import { Inspector } from "./components/inspector/Inspector";
import { BatchWizard } from "./components/jobs/BatchWizard";
import { JobsView } from "./components/jobs/JobsView";
import { OpsCenter } from "./components/opscenter/OpsCenter";
import { LoginLogView } from "./components/LoginLogView";
import { ProfilesView } from "./components/ProfilesView";
import { UsersView } from "./components/UsersView";
import { SettingsView } from "./components/SettingsView";
import { CommandPalette } from "./components/shell/CommandPalette";
import { FocusChip, type FocusState } from "./components/shell/FocusChip";
import { GroupSelector } from "./components/shell/GroupSelector";
import { Hud } from "./components/shell/Hud";
import { LoginModal } from "./components/shell/LoginModal";
import { NavRail } from "./components/shell/NavRail";
import { StatusBar } from "./components/shell/StatusBar";
import { toast, ToastHost } from "./components/shell/Toast";
import { useAuth } from "./context/AuthContext";
import { useActiveGroup, useGroupNodeIds } from "./context/GroupContext";
import { usePersistedState } from "./hooks/usePersistedState";
import { computeFleetGroupMetrics, computeGroupAttention, computeGroupStatus, scopeGatewaysToGroup } from "./components/fleet/groupStats";
import { consumeFinished } from "./opTracker";
import { t } from "./tokens";

const DATA_EVENTS = new Set([
  "node.seen",
  "position.updated",
  "telemetry.received",
  "message.received",
  "gateway.status",
  "alert.fired",
  "alert.resolved",
  "admin.operation",
  "admin.batch",
  // Diario operativo (Actividad 2.0 Fase 1): la ÚNICA fuente del feed;
  // el resto de eventos siguen usándose para invalidación y opTracker
  "activity.event",
]);

type View =
  | "ops"
  | "nodes"
  | "jobs"
  | "alerts"
  | "config"
  | "profiles"
  | "activity"
  | "gateways"
  | "users"
  | "login-log"
  | "settings";

/**
 * Workspaces (identidad v0.8): no hay "páginas" — el riel de navegación
 * cambia de instrumento sin abandonar el chasis (cabecera + barra de
 * estado siempre presentes). El Dashboard clásico y la vista Mapa suelta
 * han muerto: el Centro de Operaciones ES el mapa y ES el dashboard.
 */
const VIEWS: { id: View; label: string; icon: string }[] = [
  { id: "ops", label: "Centro", icon: "◉" },
  { id: "nodes", label: "Flota", icon: "⬡" },
  { id: "jobs", label: "Trabajos", icon: "▶" },
  { id: "alerts", label: "Alertas", icon: "⚠" },
  { id: "profiles", label: "Perfiles", icon: "⧉" },
  { id: "config", label: "Config", icon: "⚙" },
  { id: "activity", label: "Registro", icon: "▤" },
  { id: "gateways", label: "Enlaces", icon: "⛭" },
  // Autenticación: "Usuarios" solo visible si eres admin O si el sistema aún
  // está en modo abierto (así siempre hay una forma de crear el primer
  // usuario); "Accesos" solo tiene sentido estando autenticado.
  { id: "users", label: "Usuarios", icon: "👤" },
  { id: "login-log", label: "Accesos", icon: "🔑" },
  // Panel "Ajustes": umbrales operacionales editables sin redeploy — mismo
  // criterio de visibilidad que Usuarios (RequireAdminDep en el backend).
  { id: "settings", label: "Ajustes", icon: "🎚" },
];

/** Ids históricos (componentes/documentos antiguos): siguen navegando bien. */
function resolveView(v: string): View {
  if (v === "operations" || v === "batches") return "jobs";
  if (v === "dashboard" || v === "map") return "ops";
  return v as View;
}

export default function App() {
  const queryClient = useQueryClient();
  const authState = useAuth();
  const { activeGroupId, activeGroup } = useActiveGroup();
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth, refetchInterval: 15_000 });
  // Query base (sin ignorados): la usan Mapa, Centro y el feed — nunca escopada
  // al grupo activo (necesitan ver toda la red para el contexto espacial/global)
  const nodes = useQuery({ queryKey: ["nodes"], queryFn: () => fetchNodes(), refetchInterval: 30_000 });
  const [filters, setFilters] = useState<NodeFilterParams>({});
  // Query filtrada para la Flota (búsqueda avanzada M1.2 + grupo activo,
  // "Flota orientada a grupos": filtrado server-side, group_id ya existente
  // en apply_filters, M1.2 — el grupo activo manda sobre el filtro manual)
  const filteredNodes = useQuery({
    queryKey: ["nodes", filters, activeGroupId],
    queryFn: () => fetchNodes(activeGroupId != null ? { ...filters, group_id: activeGroupId } : filters),
    refetchInterval: 30_000,
  });
  // Estadísticas Multi-Gateway escopadas al grupo activo (§ GroupBar) —
  // reutiliza compute_multi_gateway_stats sin tocarlo (backend, scope_to_members)
  const groupGatewayStats = useQuery({
    queryKey: ["gateway-stats", "group", activeGroupId],
    queryFn: () => fetchGatewayStats(activeGroupId!),
    enabled: activeGroupId != null,
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
  // Soporte del shell (HUD + barra inferior + insignias del riel).
  // Hardening: los CONTADORES del shell salen de agregados reales del
  // backend (con el mismo escopado de grupo); las listas siguen existiendo
  // solo para detalle (Centro, Inspector, Trabajos), nunca para contar.
  const operations = useQuery({
    queryKey: ["operations", "shell"],
    queryFn: () => fetchOperations(undefined, 200),
    refetchInterval: 30_000,
  });
  const alertCounts = useQuery({
    queryKey: ["alert-counts", activeGroupId],
    queryFn: () => fetchAlertCounts(activeGroupId),
    refetchInterval: 15_000,
  });
  const operationCounts = useQuery({
    queryKey: ["operation-counts", activeGroupId],
    queryFn: () => fetchOperationCounts(activeGroupId),
    refetchInterval: 15_000,
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
  const [view, setView] = useState<View>("ops");
  const gatewayStats = useQuery({
    queryKey: ["gateway-stats"],
    queryFn: () => fetchGatewayStats(),
    refetchInterval: 30_000,
  });
  const [wsStatus, setWsStatus] = useState<EventsSocketStatus>({
    state: "connecting",
    disconnectedAt: null,
  });
  const [paletteOpen, setPaletteOpen] = useState(false);
  // Focus (v0.7 §7): contexto operativo deliberado — distinto de la selección
  const [focus, setFocus] = useState<FocusState | null>(null);
  const toggleFocus = useCallback((nodeId: string) => {
    setFocus((f) => (f?.id === nodeId ? null : { id: nodeId, since: Date.now() }));
  }, []);
  // Perfiles: solo se cargan cuando la paleta los necesita
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: fetchProfiles, enabled: paletteOpen });
  const [selected, setSelected] = useState<string | null>(null);
  // Selección múltiple para batches (M2)
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  // Cambiar de grupo activo limpia la selección: nodos armados en un grupo
  // dejan de ser visibles en otro, pero seguirían viajando al lote si no se
  // limpian — la misma clase de confusión de identidad que ya se corrigió
  // en BatchWizard esta sesión.
  useEffect(() => {
    setCheckedIds(new Set());
  }, [activeGroupId]);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [openBatchId, setOpenBatchId] = useState<number | null>(null);
  const [activity, setActivity] = useState<ActivityEntry[]>([]);
  const [registerTab, setRegisterTab] = usePersistedState<"activity" | "chat">("registro.tab", "activity");
  const invalidateTimer = useRef<number | null>(null);

  useEffect(() => {
    // Tormentas de eventos controladas en dos niveles:
    // 1) las queries se invalidan agrupadas en ventanas de 2s;
    // 2) el feed de actividad se acumula en un ref y se vuelca al estado
    //    como máximo 1 vez por segundo (cero peticiones HTTP).
    // El feed es el diario operativo (Actividad 2.0 Fase 1): solo entra
    // `activity.event`, ya redactado por el backend con nombres resueltos y
    // solo transiciones (los heartbeats nunca llegan como hechos).
    const pending: ActivityEntry[] = [];

    const ws = openEventsSocket((event) => {
      if (!DATA_EVENTS.has(event.event_type)) return;
      // Cierre del ciclo: toast cuando termina una operación lanzada aquí
      const finished = consumeFinished(event);
      if (finished) toast(finished.text, { kind: finished.kind });
      const entry = toEntry(event);
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
          queryClient.invalidateQueries({ queryKey: ["alert-counts"] });
          queryClient.invalidateQueries({ queryKey: ["operation-counts"] });
          // El selector de canales del Chat (y el botón "Directos", que solo
          // existe con dm_count > 0) debe descubrir canales/DM nuevos que
          // llegan en vivo — la lista de mensajes no lo necesita (stream WS).
          queryClient.invalidateQueries({ queryKey: ["chat-channels"] });
        }, 2000);
      }
    }, setWsStatus);

    const flush = window.setInterval(() => {
      if (pending.length === 0) return;
      setActivity((prev) => [...pending.splice(0), ...prev].slice(0, ACTIVITY_LIMIT));
    }, 1000);

    return () => {
      ws.close();
      window.clearInterval(flush);
      if (invalidateTimer.current != null) window.clearTimeout(invalidateTimer.current);
    };
  }, [queryClient]);

  // Registro persistente (hardening): al arrancar se siembra el buffer con el
  // histórico del backend — el diario ya no se pierde al recargar la página.
  // Merge con dedupe por event_id: lo que llegó por WS antes de resolver la
  // siembra nunca se duplica ni se pierde.
  useEffect(() => {
    let cancelled = false;
    fetchActivityLog(ACTIVITY_LIMIT)
      .then((items) => {
        if (cancelled) return;
        const seeded = items
          .map((it) => toEntry(it))
          .filter((e): e is ActivityEntry => e != null);
        setActivity((prev) => {
          const known = new Set(prev.map((e) => e.id));
          const merged = [...prev, ...seeded.filter((e) => !known.has(e.id))];
          merged.sort((a, b) => b.receivedAtMs - a.receivedAtMs);
          return merged.slice(0, ACTIVITY_LIMIT);
        });
      })
      .catch(() => {
        // Sin histórico disponible el feed en vivo sigue funcionando igual
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
  const hwModels = useMemo(
    () => [...new Set(summaries.map((s) => s.node.hw_model).filter((h): h is string => h != null))].sort(),
    [summaries],
  );

  // Grupo como contexto global (fase de cierre): HUD, StatusBar y las
  // insignias del riel son las tres superficies "siempre visibles" — deben
  // hablar del grupo activo igual que Flota/Trabajos/Alertas/Registro/Mapa,
  // o el contexto se rompe justo donde el operador mira primero. Un único
  // cálculo aquí, reutilizando groupStats.ts (GroupBar/StatusPanel) sin
  // duplicar nada: cero lógica nueva, solo un tercer consumidor.
  const groupNodeIds = useGroupNodeIds(summaries);
  const groupSummaries = useMemo(
    () => (groupNodeIds == null ? [] : summaries.filter((s) => groupNodeIds.has(s.node.node_id))),
    [summaries, groupNodeIds],
  );
  // (Hardening: los recuentos de alertas/operaciones del shell ya no se
  // derivan aquí de listas truncadas — los sirven /alerts/counts y
  // /admin/operations/counts con el mismo escopado de grupo.)
  const shellGateways = useMemo(
    () => scopeGatewaysToGroup(gateways.data ?? [], groupNodeIds, groupGatewayStats.data),
    [gateways.data, groupNodeIds, groupGatewayStats.data],
  );
  const shellGroupMetrics = useMemo(
    () => (groupNodeIds == null ? null : computeFleetGroupMetrics(groupSummaries, alerts.data ?? [])),
    [groupNodeIds, groupSummaries, alerts.data],
  );
  const shellGroupAttention = useMemo(
    () => (groupNodeIds == null || dashboard.data == null ? null : computeGroupAttention(groupSummaries, dashboard.data.thresholds)),
    [groupNodeIds, groupSummaries, dashboard.data],
  );
  const shellSummary: DashboardSummaryOut | undefined = useMemo(() => {
    if (groupNodeIds == null || dashboard.data == null || shellGroupMetrics == null) return dashboard.data;
    const lowBatteryCount = (shellGroupAttention ?? []).filter((n) => n.reasons.includes("low_battery")).length;
    return {
      ...dashboard.data,
      status: computeGroupStatus(shellGroupMetrics.criticalAlerts, shellGroupAttention?.length ?? 0),
      nodes_total: shellGroupMetrics.total,
      nodes_online: shellGroupMetrics.online,
      nodes_offline: shellGroupMetrics.total - shellGroupMetrics.online,
      offline_percent:
        shellGroupMetrics.total > 0
          ? (100 * (shellGroupMetrics.total - shellGroupMetrics.online)) / shellGroupMetrics.total
          : 0,
      low_battery_count: lowBatteryCount,
    };
  }, [groupNodeIds, dashboard.data, shellGroupMetrics, shellGroupAttention]);

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

  // Abrir un nodo = abrir el Inspector global in situ, se esté donde se esté
  // (v0.7 §8.1). NUNCA navega: el contexto no se pierde (principio 6).
  const showDetail = useCallback((nodeId: string) => {
    setSelected(nodeId);
  }, []);

  // Esc cierra el Inspector (la paleta ⌘K corta su propio Escape antes).
  // Nunca desde un campo de texto: ahí Esc pertenece al input (diario v0.7.2).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable)) {
        return;
      }
      setSelected(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // ⌖ Centrar del Inspector: si el mapa del Centro no está montado (otra
  // vista), se navega al Centro y el flyTo queda pendiente hasta onMapReady.
  const mapRef = useRef<import("leaflet").Map | null>(null);
  const pendingCenter = useRef<[number, number] | null>(null);
  const onMapReady = useCallback((map: import("leaflet").Map) => {
    mapRef.current = map;
    if (pendingCenter.current) {
      map.flyTo(pendingCenter.current, Math.max(map.getZoom(), 13));
      pendingCenter.current = null;
    }
  }, []);
  const centerOnMap = useCallback((lat: number, lng: number) => {
    setView((v) => {
      if (v === "ops" && mapRef.current) {
        mapRef.current.flyTo([lat, lng], Math.max(mapRef.current.getZoom(), 13));
        return v;
      }
      pendingCenter.current = [lat, lng];
      return "ops";
    });
  }, []);
  // "Localizar en el mapa" desde cualquier lista (Trabajos, etc.)
  const locateNode = useCallback(
    (nodeId: string) => {
      const pos = (nodes.data ?? []).find((s) => s.node.node_id === nodeId)?.last_position;
      if (pos) centerOnMap(pos.latitude, pos.longitude);
      else toast("El nodo no tiene posición conocida", { kind: "error" });
    },
    [nodes.data, centerOnMap],
  );

  const selectedSummary =
    filteredSummaries.find((s) => s.node.node_id === selected) ??
    summaries.find((s) => s.node.node_id === selected);

  // Insignias vivas del riel — mismo alcance que HUD/StatusBar (grupo activo).
  // Hardening: recuentos de agregados reales del backend, nunca de las
  // listas con limit (que se congelaban en 100/200 justo bajo carga).
  const activeAlertCount = alertCounts.data?.active ?? 0;
  const hasCritAlert = (alertCounts.data?.critical_active ?? 0) > 0;
  const activeOpsCount = operationCounts.data?.active ?? 0;
  const railItems = VIEWS.filter((v) => {
    if (v.id === "users" || v.id === "settings") return !authState.protectedMode || authState.isAdmin;
    if (v.id === "login-log") return authState.isAuthenticated;
    return true;
  }).map((v) => ({
    ...v,
    badge: v.id === "alerts" ? activeAlertCount : v.id === "jobs" ? activeOpsCount : undefined,
    badgeCrit: v.id === "alerts" && hasCritAlert,
  }));
  const currentView = VIEWS.find((v) => v.id === view);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        overflow: "hidden",
        background: "var(--chassis)",
        color: t.text,
        fontFamily: t.fontUi,
      }}
    >
      {/* Cabecera del chasis: marca + workspace actual + ⌘K + Focus + HUD.
          La navegación vive en el riel; aquí solo identidad y constantes. */}
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.9rem",
          height: "var(--header-height)",
          padding: "0 0.9rem",
          background: "var(--chassis)",
          borderBottom: `1px solid ${t.borderSubtle}`,
          flexShrink: 0,
        }}
      >
        <img
          src="/brand/logo.png"
          alt="MeshSentinel"
          onClick={() => setView("ops")}
          title="Centro de Operaciones"
          style={{
            height: "3rem",
            width: "auto",
            cursor: "pointer",
            flexShrink: 0,
          }}
        />
        <span
          className="mono"
          style={{ color: t.textFaint, fontSize: 11, letterSpacing: "0.1em", whiteSpace: "nowrap" }}
        >
          ／ {currentView?.label.toUpperCase()}
        </span>
        <button
          onClick={() => setPaletteOpen(true)}
          title="Búsqueda global (Ctrl+K / ⌘K)"
          className="btn ghost"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "0.5rem",
            minWidth: 190,
            border: `1px solid ${t.borderSubtle}`,
          }}
        >
          <span>⌕ Buscar…</span>
          <span className="mono" style={{ marginLeft: "auto", fontSize: "0.72rem", color: t.textFaint }}>⌘K</span>
        </button>
        <GroupSelector />
        <span style={{ marginLeft: "auto" }} />
        {focus && (
          <FocusChip
            focus={focus}
            label={
              summaries.find((s) => s.node.node_id === focus.id)?.node.short_name ?? focus.id
            }
            onOpen={() => setSelected(focus.id)}
            onExit={() => setFocus(null)}
          />
        )}
        <Hud
          summary={shellSummary}
          gateways={shellGateways}
          alertCounts={alertCounts.data}
          operationCounts={operationCounts.data}
          onGoTo={(v) => setView(resolveView(v))}
        />
      </header>

      {/* WS caído = estado de primera clase (§11.2): aviso fino, nunca silencio */}
      {wsStatus.state === "reconnecting" && (
        <div
          style={{
            background: t.warnTint,
            borderBottom: `1px solid ${t.warn}`,
            color: t.warn,
            padding: "0.3rem 1rem",
            fontSize: "0.85rem",
            flexShrink: 0,
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
        onNavigate={(v) => setView(resolveView(v))}
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

      {/* Cuerpo: riel de navegación + workspace activo, todo a sangre */}
      <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
        <NavRail items={railItems} active={view} onNavigate={(v) => setView(resolveView(v))} />

        <div style={{ flex: 1, minWidth: 0, minHeight: 0 }}>
          {view === "ops" && (
            <OpsCenter
              summaries={summaries}
              gatewayNodeIds={gatewayNodeIds}
              summary={dashboard.data}
              alerts={alerts.data ?? []}
              gateways={gateways.data ?? []}
              stats={gatewayStats.data}
              operations={operations.data ?? []}
              runningBatch={runningBatch.data}
              activity={activity}
              selected={selected}
              focusId={focus?.id ?? null}
              onSelect={setSelected}
              onGoTo={(v) => setView(resolveView(v))}
              onMapReady={onMapReady}
            />
          )}

          {view === "nodes" && (
            <FleetView
              summaries={filteredSummaries}
              allSummaries={summaries}
              loading={filteredNodes.isLoading}
              error={filteredNodes.isError}
              filters={filters}
              onFiltersChange={setFilters}
              tags={tags.data ?? []}
              groups={groups.data ?? []}
              gateways={gateways.data ?? []}
              gatewayNodeIds={gatewayNodeIds}
              activeGroup={activeGroup}
              groupGatewayStats={groupGatewayStats.data}
              alerts={alerts.data ?? []}
              hwModels={hwModels}
              selected={selected}
              focusId={focus?.id ?? null}
              onSelect={setSelected}
              onToggleFavorite={(id, value) => toggleFavorite.mutate({ id, value })}
              onToggleIgnored={(id, value) => toggleIgnored.mutate({ id, value })}
              checkedIds={checkedIds}
              onCheckedChange={setCheckedIds}
              onCreateBatch={() => setWizardOpen(true)}
              lowBatteryThreshold={dashboard.data?.thresholds.low_battery_percent ?? 20}
            />
          )}

          {view === "activity" && (
            <div style={{ height: "100%", minHeight: 0, display: "flex", flexDirection: "column" }}>
              <div className="toolbar">
                <span className="seg">
                  <button
                    className={registerTab === "activity" ? "on" : undefined}
                    onClick={() => setRegisterTab("activity")}
                    title="Registro cronológico completo de paquetes"
                  >
                    Actividad
                  </button>
                  <button
                    className={registerTab === "chat" ? "on" : undefined}
                    onClick={() => setRegisterTab("chat")}
                    title="Monitor de mensajes de texto de la red"
                  >
                    Chat
                  </button>
                </span>
              </div>
              <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
                {registerTab === "activity" ? (
                  <ActivityConsole entries={activity} summaries={summaries} gateways={gateways.data ?? []} />
                ) : (
                  <ChatConsole entries={activity} summaries={summaries} gateways={gateways.data ?? []} />
                )}
              </div>
            </div>
          )}

          {view === "gateways" && <GatewaysView />}

          {view === "alerts" && <AlertsView onOpenNode={setSelected} />}

          {view === "jobs" && (
            <div className="ws">
              <div className="ws-scroll legacy-chrome" style={{ padding: "0.9rem" }}>
                <JobsView
                  summaries={summaries}
                  focusId={focus?.id ?? null}
                  openBatchId={openBatchId}
                  onOpenNode={setSelected}
                  onLocate={locateNode}
                />
              </div>
            </div>
          )}

          {view === "config" && (
            <div className="ws">
              <div className="ws-scroll legacy-chrome" style={{ padding: "0.9rem" }}>
                <ConfigEditor summaries={summaries} />
              </div>
            </div>
          )}

          {view === "profiles" && (
            <div className="ws">
              <div className="ws-scroll legacy-chrome" style={{ padding: "0.9rem" }}>
                <ProfilesView
                  summaries={summaries}
                  onOpenBatch={(batchId) => {
                    setOpenBatchId(batchId);
                    setView("jobs");
                  }}
                />
              </div>
            </div>
          )}

          {view === "users" && (
            <div className="ws">
              <div className="ws-scroll">
                <UsersView />
              </div>
            </div>
          )}

          {view === "login-log" && (
            <div className="ws">
              <div className="ws-scroll">
                <LoginLogView />
              </div>
            </div>
          )}

          {view === "settings" && (
            <div className="ws">
              <div className="ws-scroll">
                <SettingsView />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Asistente de lote (M2): superpuesto al workspace, nunca una "página" */}
      {wizardOpen && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 960,
            background: "rgba(4, 6, 10, 0.72)",
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "center",
            padding: "4vh 2vw",
            overflowY: "auto",
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget) setWizardOpen(false);
          }}
        >
          <div className="legacy-chrome" style={{ width: "min(920px, 96vw)" }}>
            <BatchWizard
              selectedIds={[...checkedIds]}
              summaries={summaries}
              onDone={(batchId) => {
                setWizardOpen(false);
                if (batchId != null) {
                  setCheckedIds(new Set());
                  setOpenBatchId(batchId);
                  setView("jobs");
                }
              }}
            />
          </div>
        </div>
      )}

      {/* Inspector global (v0.9: ventana flotante): una sola ventana para
          toda la aplicación. `alerts`/`activity` sin escopar por grupo — el
          Inspector nunca oculta datos de un nodo por estar fuera del grupo
          activo, solo avisa (outsideActiveGroup, más arriba en el propio
          componente). */}
      {selected && (
        <Inspector
          nodeId={selected}
          summary={selectedSummary}
          summaries={summaries}
          operations={operations.data ?? []}
          alerts={alerts.data ?? []}
          onClose={() => setSelected(null)}
          onCenter={centerOnMap}
          onGoTo={(v) => setView(resolveView(v))}
          focusActive={focus?.id === selected}
          onToggleFocus={() => toggleFocus(selected)}
        />
      )}
      <ToastHost />
      <LoginModal />

      <StatusBar
        wsStatus={wsStatus}
        backendOk={!health.isError && health.data?.status === "ok"}
        summary={shellSummary}
        gateways={shellGateways}
        alertCounts={alertCounts.data}
        operationCounts={operationCounts.data}
        runningBatch={runningBatch.data}
        onGoTo={(v) => setView(resolveView(v))}
      />
    </div>
  );
}

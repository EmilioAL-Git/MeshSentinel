import { poll, setLiveConnected } from "./api/livePolling";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { ProfilesView } from "./components/ProfilesView";
import { StatsView } from "./components/stats/StatsView";
import { SettingsView } from "./components/SettingsView";
import { CommandPalette } from "./components/shell/CommandPalette";
import { FocusChip, type FocusState } from "./components/shell/FocusChip";
import { GroupSelector } from "./components/shell/GroupSelector";
import { Hud } from "./components/shell/Hud";
import { LoginModal } from "./components/shell/LoginModal";
import { NavRail } from "./components/shell/NavRail";
import { StatusBar } from "./components/shell/StatusBar";
import { toast, ToastHost } from "./components/shell/Toast";
import { TracerouteDialog, type TraceNodeInfo } from "./components/traceroute/TracerouteDialog";
import { useAuth } from "./context/AuthContext";
import { LockedNotice } from "./components/shell/LockedNotice";
import { useActiveGroup, useGroupNodeIds } from "./context/GroupContext";
import { usePersistedState } from "./hooks/usePersistedState";
import { useUrlFlag, useUrlNumber, useUrlParam, useUrlString, useUrlView } from "./hooks/useUrlState";
const Map3DView = lazy(() => import("./components/map3d/Map3DView").then((m) => ({ default: m.Map3DView })));
import { RAIL_VIEWS, railActive, resolveView, VIEWS, type View } from "./view";
import { ToolFrame } from "./components/tools/ToolFrame";
import { ToolsHub } from "./components/tools/ToolsHub";
import { TracesView } from "./components/tools/TracesView";
import { computeFleetGroupMetrics, computeGroupAttention, computeGroupStatus, scopeGatewaysToGroup } from "./components/fleet/groupStats";
import { consumeFinished, onTracerouteFinished, type TracerouteOutcome } from "./opTracker";
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

export default function App() {
  const queryClient = useQueryClient();
  const authState = useAuth();
  const { activeGroupId, activeGroup } = useActiveGroup();
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth, refetchInterval: 15_000 });
  // Query base (sin ignorados): la usan Mapa, Centro y el feed — nunca escopada
  // al grupo activo (necesitan ver toda la red para el contexto espacial/global)
  const nodes = useQuery({ queryKey: ["nodes"], queryFn: () => fetchNodes(), refetchInterval: poll(30_000) });
  // Filtros de Flota ↔ URL (`nodes.*`, ADR 0026 / docs/design/urls-compartibles.md
  // §3.3). Prefijo `nodes.` a propósito: `nodes.group` es el filtro puntual
  // de tabla (M1.2), distinto del grupo ACTIVO global (`group`, GroupContext)
  // — ya eran conceptos independientes antes de esta fase, el prefijo solo
  // evita que compartan nombre de parámetro.
  const [filtersQ, setFiltersQ] = useUrlString("nodes.q", null, { replace: true });
  const [filtersOnline, setFiltersOnline] = useUrlParam<boolean | undefined>("nodes.online", undefined, {
    replace: true,
    parse: (raw) => raw === "1",
    serialize: (v) => (v ? "1" : "0"),
    isDefault: (v) => v === undefined,
  });
  const [filtersFavorite, setFiltersFavorite] = useUrlFlag("nodes.favorite", { replace: true });
  const [filtersNexus, setFiltersNexus] = useUrlFlag("nodes.nexus", { replace: true });
  const [filtersHwModel, setFiltersHwModel] = useUrlString("nodes.hw", null, { replace: true });
  const [filtersTag, setFiltersTag] = useUrlString("nodes.tag", null, { replace: true });
  const [filtersGroupId, setFiltersGroupId] = useUrlNumber("nodes.group", null, { replace: true });
  const [filtersGatewayId, setFiltersGatewayId] = useUrlString("nodes.gw", null, { replace: true });
  const [filtersBatteryBelow, setFiltersBatteryBelow] = useUrlNumber("nodes.batlt", null, { replace: true });
  const [filtersIgnored, setFiltersIgnored] = useUrlFlag("nodes.ignored", { replace: true });
  const filters: NodeFilterParams = useMemo(
    () => ({
      q: filtersQ ?? undefined,
      online: filtersOnline,
      favorite: filtersFavorite || undefined,
      nexus: filtersNexus || undefined,
      hw_model: filtersHwModel ?? undefined,
      tag: filtersTag ?? undefined,
      group_id: filtersGroupId ?? undefined,
      gateway_id: filtersGatewayId ?? undefined,
      battery_below: filtersBatteryBelow ?? undefined,
      include_ignored: filtersIgnored || undefined,
    }),
    [
      filtersQ,
      filtersOnline,
      filtersFavorite,
      filtersNexus,
      filtersHwModel,
      filtersTag,
      filtersGroupId,
      filtersGatewayId,
      filtersBatteryBelow,
      filtersIgnored,
    ],
  );
  const setFilters = useCallback(
    (next: NodeFilterParams) => {
      setFiltersQ(next.q ?? null);
      setFiltersOnline(next.online);
      setFiltersFavorite(next.favorite ?? false);
      setFiltersNexus(next.nexus ?? false);
      setFiltersHwModel(next.hw_model ?? null);
      setFiltersTag(next.tag ?? null);
      setFiltersGroupId(next.group_id ?? null);
      setFiltersGatewayId(next.gateway_id ?? null);
      setFiltersBatteryBelow(next.battery_below ?? null);
      setFiltersIgnored(next.include_ignored ?? false);
    },
    [
      setFiltersQ,
      setFiltersOnline,
      setFiltersFavorite,
      setFiltersNexus,
      setFiltersHwModel,
      setFiltersTag,
      setFiltersGroupId,
      setFiltersGatewayId,
      setFiltersBatteryBelow,
      setFiltersIgnored,
    ],
  );
  // Query filtrada para la Flota (búsqueda avanzada M1.2 + grupo activo,
  // "Flota orientada a grupos": filtrado server-side, group_id ya existente
  // en apply_filters, M1.2 — el grupo activo manda sobre el filtro manual)
  const filteredNodes = useQuery({
    queryKey: ["nodes", filters, activeGroupId],
    queryFn: () => fetchNodes(activeGroupId != null ? { ...filters, group_id: activeGroupId } : filters),
    refetchInterval: poll(30_000),
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
  const gateways = useQuery({ queryKey: ["gateways"], queryFn: () => fetchGateways(), refetchInterval: poll(30_000) });
  const dashboard = useQuery({
    queryKey: ["dashboard"],
    queryFn: fetchDashboardSummary,
    refetchInterval: poll(30_000),
  });
  const alerts = useQuery({
    queryKey: ["alerts"],
    queryFn: () => fetchAlerts(undefined, 100),
    refetchInterval: poll(30_000),
  });
  // Soporte del shell (HUD + barra inferior + insignias del riel).
  // Hardening: los CONTADORES del shell salen de agregados reales del
  // backend (con el mismo escopado de grupo); las listas siguen existiendo
  // solo para detalle (Centro, Inspector, Trabajos), nunca para contar.
  const operations = useQuery({
    queryKey: ["operations", "shell"],
    queryFn: () => fetchOperations(undefined, 200),
    refetchInterval: poll(30_000),
  });
  const alertCounts = useQuery({
    queryKey: ["alert-counts", activeGroupId],
    queryFn: () => fetchAlertCounts(activeGroupId),
    refetchInterval: poll(15_000),
  });
  const operationCounts = useQuery({
    queryKey: ["operation-counts", activeGroupId],
    queryFn: () => fetchOperationCounts(activeGroupId),
    refetchInterval: poll(15_000),
  });
  const runningBatches = useQuery({
    queryKey: ["batches", "running"],
    queryFn: () => fetchBatches({ status: "running", limit: 5 }),
    refetchInterval: poll(30_000),
  });
  const runningBatchId = runningBatches.data?.[0]?.id;
  const runningBatch = useQuery({
    queryKey: ["batch", runningBatchId],
    queryFn: () => fetchBatch(runningBatchId!),
    enabled: runningBatchId != null,
    refetchInterval: 10_000,
  });
  // URLs compartibles (ADR 0026): la vista vive en el path, no en memoria.
  // `resolveView` ya traduce alias históricos (`/dashboard`, `/operations`…).
  const [view, setView] = useUrlView<View>(resolveView, "ops");
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
  // Focus (v0.7 §7): contexto operativo deliberado — distinto de la selección.
  // URLs compartibles (ADR 0026): solo el id vive en la URL (`focus=!...`,
  // replaceState); `since` es efímero, se recalcula a Date.now() cada vez
  // que el foco pasa de "sin foco" a un id (recarga con `focus` en la URL
  // incluida — igual que hoy al hacer clic en ◎).
  const [focusId, setFocusId] = useUrlString("focus", null, { replace: true });
  const focusSinceRef = useRef<{ id: string; since: number } | null>(null);
  if (!focusId) {
    focusSinceRef.current = null;
  } else if (focusSinceRef.current?.id !== focusId) {
    focusSinceRef.current = { id: focusId, since: Date.now() };
  }
  const focus: FocusState | null = focusId ? { id: focusId, since: focusSinceRef.current!.since } : null;
  const toggleFocus = useCallback(
    (nodeId: string) => setFocusId(focusId === nodeId ? null : nodeId),
    [focusId, setFocusId],
  );
  // Perfiles: solo se cargan cuando la paleta los necesita
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: fetchProfiles, enabled: paletteOpen });
  // Inspector abierto: URLs compartibles (ADR 0026) — `node=!...` en la URL,
  // pushState (abrir/cerrar el Inspector es una navegación deliberada).
  const [selected, setSelected] = useUrlString("node", null, { replace: false });
  // Resultado de un traceroute lanzado desde esta sesión: ventana sobre cualquier vista
  const [traceOutcome, setTraceOutcome] = useState<TracerouteOutcome | null>(null);
  useEffect(() => onTracerouteFinished(setTraceOutcome), []);
  const [, setM3dOp] = useUrlNumber("m3d.op");
  const [, setM3dTrace] = useUrlNumber("m3d.trace");
  const traceGateway = (gateways.data ?? []).find((g) => g.gateway_id === traceOutcome?.gatewayId) ?? null;
  const traceLookup = useCallback(
    (id: string): TraceNodeInfo | null => {
      const n = (nodes.data ?? []).find((x) => x.node.node_id === id)?.node;
      if (n) return { longName: n.long_name, shortName: n.short_name, hwModel: n.hw_model };
      if (traceGateway?.local_node_id === id) {
        return { longName: traceGateway.local_long_name, shortName: traceGateway.local_short_name, hwModel: traceGateway.local_hw_model };
      }
      return null;
    },
    [nodes.data, traceGateway],
  );
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
  // Lote abierto en Trabajos ↔ URL (`jobs.batch`, ADR 0026).
  const [openBatchId, setOpenBatchId] = useUrlNumber("jobs.batch", null, { replace: true });
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
    }, (status) => {
      setLiveConnected(status.state === "connected");
      setWsStatus(status);
    });

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
  // Salud de pasarelas = infraestructura: la barra inferior cuenta todas las
  // operativas, nunca solo las que oyen nodos del grupo activo.
  const operativeGateways = useMemo(
    () => (gateways.data ?? []).filter((g) => g.enabled && g.deleted_at == null),
    [gateways.data],
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
  // useCallback (hardening de Flota): FleetRow está memoizado con
  // React.memo — un handler nuevo en cada render de App invalidaría ese
  // memo en TODAS las filas del roster a la vez.
  const handleToggleFavorite = useCallback(
    (id: string, value: boolean) => toggleFavorite.mutate({ id, value }),
    [toggleFavorite.mutate],
  );
  const handleToggleIgnored = useCallback(
    (id: string, value: boolean) => toggleIgnored.mutate({ id, value }),
    [toggleIgnored.mutate],
  );
  const onNodesDeleted = useCallback(
    (ids: string[]) => {
      invalidateNodeData();
      setCheckedIds((prev) => {
        const next = new Set(prev);
        for (const id of ids) next.delete(id);
        return next;
      });
      if (selected != null && ids.includes(selected)) setSelected(null);
    },
    [invalidateNodeData, selected, setSelected],
  );

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
  const centerOnMap = useCallback(
    (lat: number, lng: number) => {
      if (view === "ops" && mapRef.current) {
        mapRef.current.flyTo([lat, lng], Math.max(mapRef.current.getZoom(), 13));
        return;
      }
      pendingCenter.current = [lat, lng];
      setView("ops");
    },
    [view, setView],
  );
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
  const railItems = RAIL_VIEWS.filter((v) => {
    if (v.id === "settings") return !authState.protectedMode || authState.isAdmin || authState.isAuthenticated;
    return true;
  }).map((v) => ({
    ...v,
    badge: v.id === "alerts" ? activeAlertCount : v.id === "jobs" ? activeOpsCount : undefined,
    badgeCrit: v.id === "alerts" && hasCritAlert,
  }));
  const currentView = VIEWS.find((v) => v.id === view);

  return (
    <div
      className="app-root"
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100dvh",
        overflow: "hidden",
        background: "var(--chassis)",
        color: t.text,
        fontFamily: t.fontUi,
      }}
    >
      {/* Cabecera del chasis: marca + workspace actual + ⌘K + Focus + HUD.
          La navegación vive en el riel; aquí solo identidad y constantes. */}
      <header
        className="app-header"
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
          className="app-logo"
          style={{
            height: "3rem",
            width: "auto",
            cursor: "pointer",
            flexShrink: 0,
          }}
        />
        <span
          className="mono app-viewlabel"
          style={{ color: t.textFaint, fontSize: 11, letterSpacing: "0.1em", whiteSpace: "nowrap" }}
        >
          ／ {currentView?.label.toUpperCase()}
        </span>
        <button
          onClick={() => setPaletteOpen(true)}
          title="Búsqueda global (Ctrl+K / ⌘K)"
          className="btn ghost app-search"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "0.5rem",
            minWidth: 190,
            border: `1px solid ${t.borderSubtle}`,
          }}
        >
          <span>⌕<span className="app-search-text"> Buscar…</span></span>
          <span className="mono app-search-text" style={{ marginLeft: "auto", fontSize: "0.72rem", color: t.textFaint }}>⌘K</span>
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
            onExit={() => setFocusId(null)}
          />
        )}
        <Hud
          className="app-hud"
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
      <div className="app-body" style={{ flex: 1, minHeight: 0, display: "flex" }}>
        <NavRail items={railItems} active={railActive(view)} onNavigate={(v) => setView(resolveView(v))} />

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
              onToggleFavorite={handleToggleFavorite}
              onToggleIgnored={handleToggleIgnored}
              checkedIds={checkedIds}
              onCheckedChange={setCheckedIds}
              onCreateBatch={() => setWizardOpen(true)}
              onNodesDeleted={onNodesDeleted}
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
              <div style={{ flex: 1, minHeight: 0, minWidth: 0 }}>
                {registerTab === "activity" ? (
                  <ActivityConsole entries={activity} summaries={summaries} gateways={gateways.data ?? []} />
                ) : (
                  <ChatConsole entries={activity} summaries={summaries} gateways={gateways.data ?? []} />
                )}
              </div>
            </div>
          )}

          {view === "gateways" && <GatewaysView />}

          {view === "stats" && <StatsView onOpenNode={setSelected} />}

          {view === "tools" && <ToolsHub onGoTo={(v) => setView(v)} />}

          {view === "traces" && (
            <ToolFrame title="Historial de trazas" onBack={() => setView("tools")}>
              <TracesView
                summaries={summaries}
                gateways={gateways.data ?? []}
                canOperate={authState.canOperate}
                onOpenNode={setSelected}
                onView3D={(id) => {
                  setM3dTrace(id);
                  setM3dOp(null);
                  setView("map3d");
                }}
              />
            </ToolFrame>
          )}

          {view === "map3d" && (
            <ToolFrame title="Mapa 3D" onBack={() => setView("tools")}>
              <Suspense fallback={<div className="empty">Cargando mapa 3D…</div>}>
                <Map3DView summaries={summaries} onOpenNode={setSelected} />
              </Suspense>
            </ToolFrame>
          )}

          {view === "alerts" && <AlertsView onOpenNode={setSelected} />}

          {view === "jobs" && (
            <div className="ws">
              <div className="ws-scroll legacy-chrome" style={{ padding: "0.9rem" }}>
                <JobsView
                  summaries={summaries}
                  focusId={focus?.id ?? null}
                  openBatchId={openBatchId}
                  onOpenBatchIdChange={setOpenBatchId}
                  onOpenNode={setSelected}
                  onLocate={locateNode}
                />
              </div>
            </div>
          )}

          {view === "config" && (
            <ToolFrame title="Administración remota" onBack={() => setView("tools")}>
              <div className="ws">
                <div className="ws-scroll legacy-chrome" style={{ padding: "0.9rem" }}>
                  {authState.canOperate ? (
                    <ConfigEditor summaries={summaries} />
                  ) : (
                    <LockedNotice what="La administración remota" />
                  )}
                </div>
              </div>
            </ToolFrame>
          )}

          {view === "profiles" && (
            <div className="ws">
              <div className="ws-scroll legacy-chrome" style={{ padding: "0.9rem" }}>
                <ProfilesView
                  summaries={summaries}
                  readOnly={!authState.canOperate}
                  onOpenBatch={(batchId) => {
                    setOpenBatchId(batchId);
                    setView("jobs");
                  }}
                />
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
          onDeleted={() => onNodesDeleted([selected])}
        />
      )}
      <ToastHost />
      {traceOutcome && (
        <TracerouteDialog
          outcome={traceOutcome}
          lookup={traceLookup}
          originNodeId={traceGateway?.local_node_id ?? null}
          originGatewayName={traceGateway?.name ?? traceOutcome.gatewayId}
          onOpenNode={setSelected}
          onView3D={(op) => {
            setM3dTrace(null);
            setM3dOp(op);
            setView("map3d");
          }}
          onClose={() => setTraceOutcome(null)}
        />
      )}
      <LoginModal />

      <StatusBar
        wsStatus={wsStatus}
        backendOk={!health.isError && health.data?.status === "ok"}
        summary={shellSummary}
        gateways={operativeGateways}
        alertCounts={alertCounts.data}
        operationCounts={operationCounts.data}
        runningBatch={runningBatch.data}
        onGoTo={(v) => setView(resolveView(v))}
      />
    </div>
  );
}

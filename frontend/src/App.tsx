import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchGateways, fetchHealth, fetchNodes, openEventsSocket } from "./api/client";
import { MapView } from "./components/MapView";
import { NodeDetail } from "./components/NodeDetail";
import { NodesTable } from "./components/NodesTable";
import { styles } from "./styles";

const DATA_EVENTS = new Set(["node.seen", "position.updated", "telemetry.received", "gateway.status"]);

type View = "nodes" | "map";

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
  const [view, setView] = useState<View>("nodes");
  const [selected, setSelected] = useState<string | null>(null);
  const invalidateTimer = useRef<number | null>(null);

  useEffect(() => {
    // Los eventos WS marcan los datos como obsoletos; se agrupan en una ventana
    // de 2s para no refetchear en ráfaga cuando la malla está activa.
    const ws = openEventsSocket((event) => {
      if (!DATA_EVENTS.has(event.event_type)) return;
      if (invalidateTimer.current != null) return;
      invalidateTimer.current = window.setTimeout(() => {
        invalidateTimer.current = null;
        queryClient.invalidateQueries({ queryKey: ["nodes"] });
        queryClient.invalidateQueries({ queryKey: ["gateways"] });
      }, 2000);
    });
    return () => {
      ws.close();
      if (invalidateTimer.current != null) window.clearTimeout(invalidateTimer.current);
    };
  }, [queryClient]);

  const summaries = nodes.data ?? [];
  const onlineCount = summaries.filter((s) => s.node.online).length;

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
          <NavTab active={view === "nodes"} label="Nodos" onClick={() => setView("nodes")} />
          <NavTab active={view === "map"} label="Mapa" onClick={() => setView("map")} />
        </nav>
      </div>

      <div style={{ ...styles.card, display: "flex", gap: "2rem", flexWrap: "wrap" }}>
        <span>
          Nodos: <strong>{summaries.length}</strong> ({onlineCount} online)
        </span>
        <span>
          Pasarelas:{" "}
          {(gateways.data ?? []).map((g) => (
            <span key={g.gateway_id} style={{ marginRight: "1rem" }}>
              <span style={styles.mono}>{g.gateway_id}</span>{" "}
              <span style={g.status === "connected" ? styles.ok : styles.bad}>{g.status}</span>{" "}
              <span style={styles.dim}>({g.transport})</span>
            </span>
          ))}
        </span>
        <span>
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

      {view === "map" ? (
        <MapView summaries={summaries} gatewayNodeIds={gatewayNodeIds} onShowDetail={showDetail} />
      ) : (
        <div style={selected ? styles.layout : undefined}>
          <div style={styles.card}>
            <h2 style={{ marginTop: 0 }}>Nodos descubiertos</h2>
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

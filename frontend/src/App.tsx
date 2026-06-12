import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { fetchGateways, fetchHealth, fetchNodes, openEventsSocket } from "./api/client";
import { NodeDetail } from "./components/NodeDetail";
import { NodesTable } from "./components/NodesTable";
import { styles } from "./styles";

const DATA_EVENTS = new Set(["node.seen", "position.updated", "telemetry.received", "gateway.status"]);

export default function App() {
  const queryClient = useQueryClient();
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth, refetchInterval: 15_000 });
  const nodes = useQuery({ queryKey: ["nodes"], queryFn: fetchNodes, refetchInterval: 30_000 });
  const gateways = useQuery({ queryKey: ["gateways"], queryFn: fetchGateways, refetchInterval: 30_000 });
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

  return (
    <div style={styles.page}>
      <h1 style={{ marginTop: 0 }}>Meshtastic NOC</h1>

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
    </div>
  );
}

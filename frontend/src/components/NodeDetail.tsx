import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { fetchNode, fetchNodePositions, fetchNodeTelemetry } from "../api/client";
import { styles } from "../styles";

interface Props {
  nodeId: string;
  onClose: () => void;
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <tr>
      <td style={{ ...styles.td, ...styles.dim, width: "40%" }}>{label}</td>
      <td style={styles.td}>{value ?? "—"}</td>
    </tr>
  );
}

export function NodeDetail({ nodeId, onClose }: Props) {
  const node = useQuery({ queryKey: ["node", nodeId], queryFn: () => fetchNode(nodeId), refetchInterval: 10_000 });
  const telemetry = useQuery({
    queryKey: ["telemetry", nodeId],
    queryFn: () => fetchNodeTelemetry(nodeId, 10),
    refetchInterval: 15_000,
  });
  const positions = useQuery({
    queryKey: ["positions", nodeId],
    queryFn: () => fetchNodePositions(nodeId, 10),
    refetchInterval: 15_000,
  });

  if (node.isLoading) return <div style={styles.card}>Cargando {nodeId}…</div>;
  if (node.isError || !node.data) return <div style={styles.card}>Error cargando {nodeId}</div>;

  const n = node.data;
  const lastTel = telemetry.data?.[0];
  const lastPos = positions.data?.[0];

  return (
    <div style={styles.card}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0 }}>
          {n.short_name ?? n.node_id}{" "}
          <span style={n.online ? styles.badgeOnline : styles.badgeOffline}>
            {n.online ? "online" : "offline"}
          </span>
        </h2>
        <button onClick={onClose} style={{ background: "none", border: "1px solid #30363d", color: "#e6edf3", borderRadius: 6, cursor: "pointer", padding: "0.2rem 0.6rem" }}>
          ✕
        </button>
      </div>
      <table style={styles.table}>
        <tbody>
          <Row label="ID" value={<span style={styles.mono}>{n.node_id}</span>} />
          <Row label="Nombre" value={n.long_name} />
          <Row label="Hardware" value={n.hw_model} />
          <Row label="Firmware" value={n.firmware_version} />
          <Row label="Rol" value={n.role} />
          <Row label="SNR / RSSI" value={`${n.snr ?? "—"} dB / ${n.rssi ?? "—"} dBm`} />
          <Row label="Saltos" value={n.hops_away} />
          <Row label="Pasarela" value={n.gateway_id} />
          <Row label="Primera vez visto" value={n.first_seen_at ? new Date(n.first_seen_at).toLocaleString() : null} />
          <Row label="Última vez visto" value={n.last_seen_at ? new Date(n.last_seen_at).toLocaleString() : null} />
        </tbody>
      </table>

      <h3>Telemetría</h3>
      {lastTel ? (
        <table style={styles.table}>
          <tbody>
            <Row label="Batería" value={lastTel.battery_level != null ? (lastTel.battery_level > 100 ? "Alimentación externa" : `${lastTel.battery_level}%`) : null} />
            <Row label="Voltaje" value={lastTel.voltage != null ? `${lastTel.voltage} V` : null} />
            <Row label="Uso de canal" value={lastTel.channel_utilization != null ? `${lastTel.channel_utilization}%` : null} />
            <Row label="Air util TX" value={lastTel.air_util_tx != null ? `${lastTel.air_util_tx}%` : null} />
            <Row label="Uptime" value={lastTel.uptime_seconds != null ? `${Math.round(lastTel.uptime_seconds / 3600)}h` : null} />
          </tbody>
        </table>
      ) : (
        <p style={styles.dim}>Sin telemetría registrada.</p>
      )}

      <h3>Última posición</h3>
      {lastPos ? (
        <table style={styles.table}>
          <tbody>
            <Row label="Coordenadas" value={<span style={styles.mono}>{lastPos.latitude.toFixed(6)}, {lastPos.longitude.toFixed(6)}</span>} />
            <Row label="Altitud" value={lastPos.altitude_m != null ? `${lastPos.altitude_m} m` : null} />
            <Row label="Satélites" value={lastPos.sats_in_view} />
            <Row label="Recibida" value={lastPos.received_at ? new Date(lastPos.received_at).toLocaleString() : null} />
          </tbody>
        </table>
      ) : (
        <p style={styles.dim}>Sin posiciones registradas (nodo sin GPS o aún sin difundir).</p>
      )}
    </div>
  );
}

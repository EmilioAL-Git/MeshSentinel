import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type CSSProperties, type ReactNode } from "react";
import {
  addGroupMember,
  createGroup,
  createTag,
  fetchGroups,
  fetchKnownRemoteFlags,
  fetchNode,
  fetchNodeGateways,
  fetchNodePositions,
  fetchNodeTelemetry,
  fetchTags,
  queueRemoteFlag,
  removeGroupMember,
  resendPendingRemoteFlags,
  setNodeFavorite,
  setNodeIgnored,
  setNodeTags,
  syncRemoteFlags,
  type NodeSummaryOut,
  type RemoteFlagSyncState,
  type RemoteFlagType,
} from "../api/client";
import { NodeSelect } from "./NodeSelect";
import { styles } from "../styles";

interface Props {
  nodeId: string;
  summary?: NodeSummaryOut;
  summaries?: NodeSummaryOut[];
  onClose: () => void;
}

const SYNC_STATE_LABEL: Record<RemoteFlagSyncState, string> = {
  pending: "Pendiente",
  sent: "Enviado",
  confirmed: "Confirmado",
  error: "Error",
};

const SYNC_STATE_COLOR: Record<RemoteFlagSyncState, string> = {
  pending: "#8b949e",
  sent: "#1f6feb",
  confirmed: "#1f6f43",
  error: "#cf222e",
};

function SyncBadge({ state }: { state: RemoteFlagSyncState }) {
  return (
    <span
      style={{
        background: SYNC_STATE_COLOR[state],
        color: "#fff",
        borderRadius: 12,
        padding: "0.1rem 0.6rem",
        fontSize: "0.75rem",
      }}
      title="«Confirmado» = el firmware aceptó la operación (ACK). El NOC no puede releer la NodeDB remota del nodo destino para verificarlo."
    >
      {SYNC_STATE_LABEL[state]}
    </span>
  );
}

const btn: CSSProperties = {
  background: "none",
  border: "1px solid #30363d",
  color: "#e6edf3",
  borderRadius: 6,
  cursor: "pointer",
  padding: "0.2rem 0.6rem",
};

// ── Favoritos/ignorados remotos (M4.2, ADR 0020) ───────────────────────────
// Toda la decisión de qué operación enviar vive en el backend
// (remote_flag_sync.py); este panel solo dispara acciones e invalida caché.
function RemoteFlagPanel({
  nodeId,
  flagType,
  label,
  subjectOptions,
}: {
  nodeId: string;
  flagType: RemoteFlagType;
  label: string;
  subjectOptions: NodeSummaryOut[];
}) {
  const queryClient = useQueryClient();
  const [subjectNodeId, setSubjectNodeId] = useState("");
  const [sendContact, setSendContact] = useState(false);

  const invalidateFlag = () => {
    queryClient.invalidateQueries({ queryKey: ["remote-flags-known", nodeId, flagType] });
    queryClient.invalidateQueries({ queryKey: ["batches"] });
    queryClient.invalidateQueries({ queryKey: ["operations"] });
  };

  const known = useQuery({
    queryKey: ["remote-flags-known", nodeId, flagType],
    queryFn: () => fetchKnownRemoteFlags(nodeId, flagType),
    refetchInterval: 5_000,
  });

  const queueFlag = useMutation({
    mutationFn: (vars: { action: "set" | "remove"; subjectId: string }) =>
      queueRemoteFlag(nodeId, {
        flag_type: flagType,
        action: vars.action,
        subject_node_id: vars.subjectId,
        send_contact: sendContact,
      }),
    onSettled: invalidateFlag,
  });

  const sync = useMutation({
    mutationFn: () => syncRemoteFlags(nodeId, { flag_type: flagType, send_contact: sendContact }),
    onSettled: invalidateFlag,
  });

  const resend = useMutation({
    mutationFn: () => resendPendingRemoteFlags(nodeId, flagType),
    onSettled: invalidateFlag,
  });

  const rows = (known.data ?? []).filter((r) => r.latest_action === "set");

  return (
    <div style={{ marginBottom: "1.2rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h4 style={{ margin: "0.4rem 0" }}>{label}</h4>
        <span>
          <button style={{ ...btn, marginRight: 6 }} disabled={sync.isPending} onClick={() => sync.mutate()}>
            Sincronizar
          </button>
          <button style={btn} disabled={resend.isPending} onClick={() => resend.mutate()}>
            Reenviar pendientes
          </button>
        </span>
      </div>
      <table style={styles.table}>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td style={{ ...styles.td, ...styles.dim }} colSpan={3}>
                Ninguno conocido todavía.
              </td>
            </tr>
          )}
          {rows.map((r) => (
            <tr key={r.subject_node_id}>
              <td style={styles.td}>{r.subject_display_name ?? r.subject_node_id}</td>
              <td style={{ ...styles.td, ...styles.mono }}>{r.subject_node_id}</td>
              <td style={styles.td}>
                <SyncBadge state={r.sync_state} />
                <button
                  style={{ ...btn, marginLeft: 8 }}
                  disabled={queueFlag.isPending}
                  onClick={() => queueFlag.mutate({ action: "remove", subjectId: r.subject_node_id })}
                >
                  Eliminar
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center", marginTop: "0.4rem" }}>
        <NodeSelect
          value={subjectNodeId}
          onChange={setSubjectNodeId}
          options={subjectOptions}
          placeholder="— nodo sujeto —"
        />
        <button
          style={btn}
          disabled={!subjectNodeId || queueFlag.isPending}
          onClick={() => {
            queueFlag.mutate({ action: "set", subjectId: subjectNodeId });
            setSubjectNodeId("");
          }}
        >
          Añadir
        </button>
        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: "0.85rem" }}>
          <input type="checkbox" checked={sendContact} onChange={(e) => setSendContact(e.target.checked)} />
          Enviar previamente la ficha de contacto del nodo seleccionado
        </label>
      </div>
      {(queueFlag.isError || sync.isError || resend.isError) && (
        <p style={styles.bad}>Error al procesar la operación.</p>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <tr>
      <td style={{ ...styles.td, ...styles.dim, width: "40%" }}>{label}</td>
      <td style={styles.td}>{value ?? "—"}</td>
    </tr>
  );
}

export function NodeDetail({ nodeId, summary, summaries = [], onClose }: Props) {
  const queryClient = useQueryClient();
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["node", nodeId] });
    queryClient.invalidateQueries({ queryKey: ["nodes"] });
    queryClient.invalidateQueries({ queryKey: ["tags"] });
    queryClient.invalidateQueries({ queryKey: ["groups"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  };

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
  const gatewayLinks = useQuery({
    queryKey: ["node-gateways", nodeId],
    queryFn: () => fetchNodeGateways(nodeId),
    refetchInterval: 15_000,
  });
  const allTags = useQuery({ queryKey: ["tags"], queryFn: fetchTags });
  const allGroups = useQuery({ queryKey: ["groups"], queryFn: fetchGroups });

  const favorite = useMutation({
    mutationFn: (value: boolean) => setNodeFavorite(nodeId, value),
    onSettled: invalidate,
  });
  const ignored = useMutation({
    mutationFn: (value: boolean) => setNodeIgnored(nodeId, value),
    onSettled: invalidate,
  });
  const saveTags = useMutation({
    mutationFn: (tagIds: number[]) => setNodeTags(nodeId, tagIds),
    onSettled: invalidate,
  });
  const newTag = useMutation({
    mutationFn: async (name: string) => {
      const tag = await createTag(name);
      const current = (summary?.tags ?? []).map((t) => t.id);
      await setNodeTags(nodeId, [...current, tag.id]);
    },
    onSettled: invalidate,
  });
  const membership = useMutation({
    mutationFn: ({ groupId, member }: { groupId: number; member: boolean }) =>
      member ? addGroupMember(groupId, nodeId) : removeGroupMember(groupId, nodeId),
    onSettled: invalidate,
  });
  const newGroup = useMutation({
    mutationFn: async (name: string) => {
      const group = await createGroup(name);
      await addGroupMember(group.id, nodeId);
    },
    onSettled: invalidate,
  });

  const [tagInput, setTagInput] = useState("");
  const [groupInput, setGroupInput] = useState("");

  const subjectOptions = summaries.filter((s) => s.node.node_id !== nodeId);

  if (node.isLoading) return <div style={styles.card}>Cargando {nodeId}…</div>;
  if (node.isError || !node.data) return <div style={styles.card}>Error cargando {nodeId}</div>;

  const n = node.data;
  const lastTel = telemetry.data?.[0];
  const lastPos = positions.data?.[0];
  const nodeTagIds = new Set((summary?.tags ?? []).map((t) => t.id));
  const nodeGroupIds = new Set(summary?.group_ids ?? []);

  return (
    <div style={styles.card}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0 }}>
          <span
            title={n.is_favorite ? "Quitar de favoritos" : "Marcar favorito"}
            style={{ cursor: "pointer", color: n.is_favorite ? "#e3b341" : "#484f58" }}
            onClick={() => favorite.mutate(!n.is_favorite)}
          >
            {n.is_favorite ? "★" : "☆"}
          </span>{" "}
          {n.short_name ?? n.node_id}{" "}
          <span style={n.online ? styles.badgeOnline : styles.badgeOffline}>
            {n.online ? "online" : "offline"}
          </span>
        </h2>
        <span>
          <button
            onClick={() => ignored.mutate(!n.is_ignored)}
            style={{ ...btn, marginRight: 6, color: n.is_ignored ? "#f85149" : "#e6edf3" }}
          >
            {n.is_ignored ? "Dejar de ignorar" : "Ignorar"}
          </button>
          <button onClick={onClose} style={btn}>✕</button>
        </span>
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
          <Row label="Pasarela primaria" value={n.gateway_id} />
          <Row label="Primera vez visto" value={n.first_seen_at ? new Date(n.first_seen_at).toLocaleString() : null} />
          <Row label="Última vez visto" value={n.last_seen_at ? new Date(n.last_seen_at).toLocaleString() : null} />
        </tbody>
      </table>

      <h3>Observaciones por pasarela</h3>
      {(gatewayLinks.data ?? []).length === 0 ? (
        <p style={styles.dim}>Ninguna pasarela ha registrado todavía una recepción directa de este nodo.</p>
      ) : (
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>Pasarela</th>
              <th style={styles.th}>SNR</th>
              <th style={styles.th}>RSSI</th>
              <th style={styles.th}>Saltos</th>
              <th style={styles.th}>Última escucha</th>
              <th style={styles.th}>Estado</th>
            </tr>
          </thead>
          <tbody>
            {(gatewayLinks.data ?? []).map((l) => (
              <tr key={l.gateway_id} style={{ opacity: l.active ? 1 : 0.55 }}>
                <td style={{ ...styles.td, ...styles.mono }}>
                  {l.gateway_id}
                  {l.primary && (
                    <span title="Pasarela primaria del nodo" style={{ color: "#e3b341", marginLeft: 6 }}>
                      ◆ primaria
                    </span>
                  )}
                </td>
                <td style={styles.td}>{l.snr != null ? `${l.snr} dB` : "—"}</td>
                <td style={styles.td}>{l.rssi != null ? `${l.rssi} dBm` : "—"}</td>
                <td style={styles.td}>{l.hops_away ?? "—"}</td>
                <td style={styles.td}>{l.last_heard_at ? new Date(l.last_heard_at).toLocaleString() : "—"}</td>
                <td style={styles.td}>
                  {l.active ? (
                    <span style={styles.badgeOnline}>activo</span>
                  ) : (
                    <span style={styles.badgeOffline}>sin escucha reciente</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

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

      <h3>Etiquetas</h3>
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
        {(allTags.data ?? []).map((t) => (
          <label key={t.id} style={{ display: "flex", alignItems: "center", gap: 3 }}>
            <input
              type="checkbox"
              checked={nodeTagIds.has(t.id)}
              onChange={(e) => {
                const next = new Set(nodeTagIds);
                if (e.target.checked) next.add(t.id);
                else next.delete(t.id);
                saveTags.mutate([...next]);
              }}
            />
            {t.name}
          </label>
        ))}
        <input
          style={{ background: "#0d1117", border: "1px solid #30363d", color: "#e6edf3", borderRadius: 6, padding: "0.2rem 0.4rem", width: 120 }}
          placeholder="nueva etiqueta"
          value={tagInput}
          onChange={(e) => setTagInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && tagInput.trim()) {
              newTag.mutate(tagInput.trim());
              setTagInput("");
            }
          }}
        />
      </div>

      <h3>Grupos</h3>
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
        {(allGroups.data ?? []).map((g) => (
          <label key={g.id} style={{ display: "flex", alignItems: "center", gap: 3 }}>
            <input
              type="checkbox"
              checked={nodeGroupIds.has(g.id)}
              onChange={(e) => membership.mutate({ groupId: g.id, member: e.target.checked })}
            />
            {g.name} <span style={styles.dim}>({g.member_count})</span>
          </label>
        ))}
        <input
          style={{ background: "#0d1117", border: "1px solid #30363d", color: "#e6edf3", borderRadius: 6, padding: "0.2rem 0.4rem", width: 120 }}
          placeholder="nuevo grupo"
          value={groupInput}
          onChange={(e) => setGroupInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && groupInput.trim()) {
              newGroup.mutate(groupInput.trim());
              setGroupInput("");
            }
          }}
        />
      </div>

      <h3>Favoritos / ignorados remotos</h3>
      <p style={{ ...styles.dim, fontSize: "0.8rem" }}>
        Administra la NodeDB del firmware de <strong>este</strong> nodo: qué otros nodos deben
        aparecer como favoritos o ignorados en su pantalla. Se encola como operaciones admin
        (pipeline y Batches existentes) — no tiene relación con el ★/ojo locales de arriba, que
        son solo de organización del NOC. «Sincronizar» solo genera lo necesario para alcanzar
        el estado deseado; «Reenviar pendientes» solo reintenta lo Pendiente o en Error.
      </p>
      <RemoteFlagPanel nodeId={nodeId} flagType="favorite" label="Favoritos conocidos" subjectOptions={subjectOptions} />
      <RemoteFlagPanel nodeId={nodeId} flagType="ignored" label="Ignorados conocidos" subjectOptions={subjectOptions} />
    </div>
  );
}

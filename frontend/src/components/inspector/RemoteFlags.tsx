import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type CSSProperties } from "react";
import {
  fetchKnownRemoteFlags,
  queueRemoteFlag,
  resendPendingRemoteFlags,
  syncRemoteFlags,
  type NodeSummaryOut,
  type RemoteFlagSyncState,
  type RemoteFlagType,
} from "../../api/client";
import { chipStyle, t } from "../../tokens";
import { NodeSelect } from "../NodeSelect";
import { toast } from "../shell/Toast";

/**
 * Favoritos/ignorados remotos (M4.2, ADR 0020) dentro del Inspector.
 * Administra la NodeDB del firmware del nodo INSPECCIONADO — nada que ver
 * con el ★/ojo locales de organización del NOC. Toda la decisión de qué
 * operación enviar vive en el backend (remote_flag_sync.py); este panel
 * solo dispara acciones e invalida caché. Vocabulario de operador
 * (Pendiente/Enviado/Confirmado/Error), nunca estados de contrato.
 */

const SYNC_STATE_LABEL: Record<RemoteFlagSyncState, string> = {
  pending: "Pendiente",
  sent: "Enviado",
  confirmed: "Confirmado",
  error: "Error",
};

const SYNC_STATE_COLOR: Record<RemoteFlagSyncState, string> = {
  pending: t.textDim,
  sent: t.accent,
  confirmed: t.ok,
  error: t.crit,
};

const btn: CSSProperties = {
  background: "transparent",
  border: `1px solid ${t.border}`,
  color: t.text,
  borderRadius: 4,
  cursor: "pointer",
  fontSize: 11,
  padding: "0.1rem 0.5rem",
};

function RemoteFlagList({
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
    onSuccess: () => toast("Operación añadida a la cola"),
    onError: () => toast("No se pudo encolar la operación", { kind: "error" }),
    onSettled: invalidateFlag,
  });

  const sync = useMutation({
    mutationFn: () => syncRemoteFlags(nodeId, { flag_type: flagType, send_contact: sendContact }),
    onSuccess: (r) => toast(r.items > 0 ? `Sincronización encolada (${r.items} operaciones)` : "Ya estaba todo al día"),
    onError: () => toast("No se pudo sincronizar", { kind: "error" }),
    onSettled: invalidateFlag,
  });

  const resend = useMutation({
    mutationFn: () => resendPendingRemoteFlags(nodeId, flagType),
    onSuccess: (r) => toast(r.items > 0 ? `Reenvío encolado (${r.items} operaciones)` : "Nada pendiente de reenviar"),
    onError: () => toast("No se pudo reenviar", { kind: "error" }),
    onSettled: invalidateFlag,
  });

  const rows = (known.data ?? []).filter((r) => r.latest_action === "set");

  return (
    <div style={{ marginBottom: "0.8rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: 4 }}>
        <span style={{ color: t.textDim, fontSize: 11.5, fontWeight: 600 }}>{label}</span>
        <span style={{ marginLeft: "auto", display: "inline-flex", gap: 4 }}>
          <button style={btn} disabled={sync.isPending} onClick={() => sync.mutate()} title="Genera solo lo necesario para alcanzar el estado deseado">
            Sincronizar
          </button>
          <button style={btn} disabled={resend.isPending} onClick={() => resend.mutate()} title="Reintenta solo lo Pendiente o en Error">
            Reenviar
          </button>
        </span>
      </div>
      {rows.length === 0 && <div style={{ color: t.textFaint, fontSize: 12 }}>Ninguno conocido todavía.</div>}
      {rows.map((r) => (
        <div key={r.subject_node_id} style={{ display: "flex", alignItems: "center", gap: "0.45rem", padding: "0.15rem 0", fontSize: 12 }}>
          <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {r.subject_display_name ?? r.subject_node_id}
          </span>
          <span
            style={{ ...chipStyle(SYNC_STATE_COLOR[r.sync_state]), fontSize: 10.5 }}
            title="«Confirmado» = el firmware aceptó la operación (ACK). El NOC no puede releer la NodeDB remota para verificarlo."
          >
            {SYNC_STATE_LABEL[r.sync_state]}
          </span>
          <button
            style={btn}
            disabled={queueFlag.isPending}
            onClick={() => queueFlag.mutate({ action: "remove", subjectId: r.subject_node_id })}
          >
            Quitar
          </button>
        </div>
      ))}
      <div style={{ display: "flex", gap: "0.4rem", alignItems: "center", marginTop: 6, flexWrap: "wrap" }}>
        <NodeSelect value={subjectNodeId} onChange={setSubjectNodeId} options={subjectOptions} placeholder="— añadir nodo —" />
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
      </div>
      <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11.5, color: t.textDim, marginTop: 4 }}>
        <input type="checkbox" checked={sendContact} onChange={(e) => setSendContact(e.target.checked)} />
        Enviar previamente la ficha de contacto del nodo seleccionado
      </label>
    </div>
  );
}

export function RemoteFlags({ nodeId, subjectOptions }: { nodeId: string; subjectOptions: NodeSummaryOut[] }) {
  return (
    <>
      <p style={{ color: t.textFaint, fontSize: 11.5, margin: "0 0 0.6rem" }}>
        Administra la NodeDB del firmware de este nodo (qué otros nodos ve como favoritos o
        ignorados en su pantalla). Sin relación con el ★/ojo locales del NOC.
      </p>
      <RemoteFlagList nodeId={nodeId} flagType="favorite" label="Favoritos conocidos" subjectOptions={subjectOptions} />
      <RemoteFlagList nodeId={nodeId} flagType="ignored" label="Ignorados conocidos" subjectOptions={subjectOptions} />
    </>
  );
}

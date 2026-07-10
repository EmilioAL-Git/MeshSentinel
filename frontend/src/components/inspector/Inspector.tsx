import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type CSSProperties, type ReactNode } from "react";
import {
  addGroupMember,
  createGroup,
  createOperation,
  createTag,
  fetchGroups,
  fetchNode,
  fetchNodeGateways,
  fetchNodePositions,
  fetchNodeTelemetry,
  fetchTags,
  refreshNodeConfig,
  removeGroupMember,
  retryOperation,
  setNodeFavorite,
  setNodeIgnored,
  setNodeTags,
  type NodeSummaryOut,
  type OperationOut,
} from "../../api/client";
import { relativeTime } from "../../time";
import { chipStyle, t } from "../../tokens";
import { trackOperations } from "../../opTracker";
import {
  OP_STATUS_COLOR,
  OP_STATUS_LABEL,
  RETRYABLE_OP_STATUSES as RETRYABLE,
} from "../jobs/status";
import { BlockAccordion } from "../shell/BlockAccordion";
import { toast } from "../shell/Toast";
import { RemoteFlags } from "./RemoteFlags";

/**
 * El Inspector (v0.7 §8.1): EL punto central de interacción con un nodo.
 * Un solo cajón global, abierto igual desde mapa, listas, alertas, consola
 * o ⌘K — cabecera fija con las constantes vitales, acciones rápidas a un
 * clic (GETs con toast; los SETs mantienen su flujo con confirmación) y
 * secciones plegables con persistencia para minimizar scroll.
 * Sustituye por completo al NodeDetail heredado.
 */

const iconBtn: CSSProperties = {
  background: "transparent",
  border: `1px solid ${t.border}`,
  color: t.text,
  borderRadius: 4,
  cursor: "pointer",
  fontSize: 12,
  padding: "0.1rem 0.45rem",
};

const actionBtn: CSSProperties = {
  ...iconBtn,
  fontSize: 11.5,
  padding: "0.22rem 0.6rem",
};

const inputStyle: CSSProperties = {
  background: t.bg,
  border: `1px solid ${t.border}`,
  color: t.text,
  borderRadius: 4,
  padding: "0.15rem 0.4rem",
  fontSize: 12,
  width: 110,
};

/** Celda de la rejilla de constantes vitales de la cabecera. */
function Vital({ label, value, color }: { label: string; value: ReactNode; color?: string }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ color: t.textFaint, fontSize: 9.5, letterSpacing: "0.07em" }}>{label}</div>
      <div
        style={{
          color: color ?? t.text,
          fontFamily: t.fontMono,
          fontSize: 12,
          fontVariantNumeric: "tabular-nums",
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {value}
      </div>
    </div>
  );
}

function copy(text: string, what: string) {
  navigator.clipboard?.writeText(text).then(
    () => toast(`${what} copiado`),
    () => toast(`No se pudo copiar`, { kind: "error" }),
  );
}

export function Inspector({
  nodeId,
  summary,
  summaries,
  operations,
  onClose,
  onCenter,
  onGoTo,
  focusActive,
  onToggleFocus,
}: {
  nodeId: string;
  summary: NodeSummaryOut | undefined;
  summaries: NodeSummaryOut[];
  operations: OperationOut[];
  onClose: () => void;
  onCenter: ((lat: number, lng: number) => void) | null;
  onGoTo: (view: string) => void;
  /** Focus (§7): true si ESTE nodo es el objetivo actual. */
  focusActive: boolean;
  onToggleFocus: () => void;
}) {
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
      const current = (summary?.tags ?? []).map((x) => x.id);
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

  // Acciones rápidas: GETs a 1 clic + toast (§9). Los SETs jamás desde aquí.
  const askMetadata = useMutation({
    mutationFn: () => createOperation({ node_id: nodeId, operation_type: "metadata.get" }),
    onSuccess: (op) => {
      trackOperations([op.id]); // toast de cierre cuando termine (opTracker)
      toast(`metadata.get añadida a la cola (op #${op.id})`);
    },
    onError: (e) => toast(`No se pudo encolar: ${e.message}`, { kind: "error" }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["operations"] }),
  });
  const refreshConfig = useMutation({
    mutationFn: () => refreshNodeConfig(nodeId),
    onSuccess: (r) => {
      trackOperations(r.operation_ids);
      toast(`Lectura de configuración encolada (${r.operation_ids.length} operaciones)`);
    },
    onError: (e) => toast(`No se pudo encolar: ${e.message}`, { kind: "error" }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["operations"] }),
  });
  const doRetry = useMutation({
    mutationFn: (id: number) => retryOperation(id),
    onSuccess: () => toast("Reintento encolado"),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["operations"] }),
  });

  const [tagInput, setTagInput] = useState("");
  const [groupInput, setGroupInput] = useState("");

  const n = node.data;
  const lastTel = telemetry.data?.[0];
  const lastPos = positions.data?.[0];
  const links = gatewayLinks.data ?? [];
  const activeLinks = links.filter((l) => l.active);
  const nodeOps = operations.filter((o) => o.target_node_id === nodeId).slice(0, 5);
  const nodeTagIds = new Set((summary?.tags ?? []).map((x) => x.id));
  const nodeGroupIds = new Set(summary?.group_ids ?? []);
  const subjectOptions = summaries.filter((s) => s.node.node_id !== nodeId);

  const battery = lastTel?.battery_level;
  const batteryText =
    battery == null ? "—" : battery > 100 ? "⚡ ext." : `${battery} %`;
  const batteryColor = battery != null && battery <= 100 && battery < 25 ? t.crit : undefined;

  return (
    <aside
      style={{
        position: "fixed",
        top: "var(--header-height)",
        right: 0,
        bottom: "var(--statusbar-height)",
        width: "min(440px, 94vw)",
        background: t.bg,
        borderLeft: `1px solid ${t.border}`,
        boxShadow: "-10px 0 30px rgba(0, 0, 0, 0.5)",
        zIndex: 920,
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Cabecera fija: identidad + constantes vitales + acciones rápidas */}
      <header style={{ background: t.surface, borderBottom: `1px solid ${t.border}`, padding: "0.6rem 0.9rem 0.55rem", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: "0.5rem" }}>
          <span style={{ color: n?.online ? t.ok : t.textFaint, fontSize: 11 }}>●</span>
          <span style={{ fontWeight: 700, fontSize: 15 }}>{n?.short_name ?? nodeId}</span>
          <span style={{ color: t.textDim, fontSize: 12.5, flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {n?.long_name ?? ""}
          </span>
          <button style={{ ...iconBtn, border: "none", fontSize: 14 }} onClick={onClose} title="Cerrar (Esc)">
            ✕
          </button>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.45rem", marginTop: 3 }}>
          <span
            onClick={() => copy(nodeId, "node_id")}
            title="Copiar node_id"
            style={{ fontFamily: t.fontMono, fontSize: 11.5, color: t.textDim, cursor: "pointer" }}
          >
            {nodeId} ⧉
          </span>
          <span style={{ color: t.textFaint, fontSize: 11 }}>
            {n?.hw_model ?? "—"} · fw {n?.firmware_version ?? "—"}
            {n?.role ? ` · ${n.role}` : ""}
          </span>
          <span style={{ marginLeft: "auto", display: "inline-flex", gap: 4 }}>
            <button
              style={{
                ...iconBtn,
                color: focusActive ? t.accent : t.textFaint,
                borderColor: focusActive ? t.accent : t.border,
                background: focusActive ? t.accentTint : "transparent",
              }}
              title={
                focusActive
                  ? "Salir de Focus"
                  : "Enfocar: el mapa, la actividad y los trabajos priorizan este nodo (nada se oculta)"
              }
              onClick={onToggleFocus}
            >
              ◎
            </button>
            <button
              style={{ ...iconBtn, color: n?.is_favorite ? t.warn : t.textFaint }}
              title={n?.is_favorite ? "Quitar de favoritos (local)" : "Marcar favorito (local)"}
              onClick={() => favorite.mutate(!n?.is_favorite)}
            >
              {n?.is_favorite ? "★" : "☆"}
            </button>
            <button
              style={{ ...iconBtn, color: n?.is_ignored ? t.crit : t.textFaint }}
              title={n?.is_ignored ? "Dejar de ignorar (local)" : "Ignorar (local)"}
              onClick={() => ignored.mutate(!n?.is_ignored)}
            >
              👁
            </button>
            {onCenter && lastPos && (
              <button style={iconBtn} title="Centrar en el mapa" onClick={() => onCenter(lastPos.latitude, lastPos.longitude)}>
                ⌖
              </button>
            )}
          </span>
        </div>
        {/* Constantes vitales */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "0.5rem", marginTop: 8 }}>
          <Vital label="BATERÍA" value={batteryText} color={batteryColor} />
          <Vital label="SNR / RSSI" value={`${n?.snr ?? "—"} dB · ${n?.rssi ?? "—"}`} />
          <Vital label="SALTOS" value={n?.hops_away ?? "—"} />
          <Vital label="VISTO" value={relativeTime(n?.last_seen_at)} />
        </div>
        {/* Acciones rápidas */}
        <div style={{ display: "flex", gap: 6, marginTop: 9 }}>
          <button style={actionBtn} disabled={askMetadata.isPending} onClick={() => askMetadata.mutate()} title="Encola metadata.get (solo lectura)">
            ⚙ Pedir metadata
          </button>
          <button style={actionBtn} disabled={refreshConfig.isPending} onClick={() => refreshConfig.mutate()} title="Encola la lectura de todas las secciones de configuración (solo lectura)">
            ⟳ Leer configuración
          </button>
          <button style={{ ...actionBtn, marginLeft: "auto" }} onClick={() => onGoTo("config")} title="Editor de configuración completo (con confirmación)">
            ✎ Configurar…
          </button>
        </div>
        {n?.is_ignored && (
          <div style={{ ...chipStyle(t.textDim), display: "inline-block", marginTop: 8, fontSize: 10.5 }}>
            nodo ignorado — fuera de agregados y alertas
          </div>
        )}
      </header>

      {/* Cuerpo: secciones plegables (persistidas) */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {node.isError && <p style={{ color: t.crit, padding: "0.8rem" }}>Error cargando {nodeId}</p>}

        <BlockAccordion id="insp.gateways" title="Pasarelas" icon="🛰" count={activeLinks.length}>
          {links.length === 0 && (
            <div style={{ color: t.textFaint, fontSize: 12 }}>Ninguna recepción directa registrada todavía.</div>
          )}
          {links.map((l) => (
            <div key={l.gateway_id} style={{ display: "flex", alignItems: "baseline", gap: "0.45rem", padding: "0.16rem 0", fontSize: 12, opacity: l.active ? 1 : 0.55 }}>
              <span style={{ color: l.active ? t.ok : t.textFaint, fontSize: 9 }}>●</span>
              <span style={{ fontFamily: t.fontMono }}>{l.gateway_id}</span>
              {l.primary && (
                <span style={{ color: t.warn, fontSize: 11 }} title="Pasarela primaria (mejor señal activa)">
                  ◆
                </span>
              )}
              <span style={{ color: t.textDim, fontFamily: t.fontMono, fontSize: 11, marginLeft: "auto" }}>
                {l.snr != null ? `${l.snr} dB` : "—"} · {l.rssi != null ? `${l.rssi} dBm` : "—"} ·{" "}
                {l.hops_away != null ? `${l.hops_away} saltos` : "—"} · {relativeTime(l.last_heard_at)}
              </span>
            </div>
          ))}
          {/* Hueco preparado (docs/roadmap.md §1): aquí vivirá la pasarela
              preferida del nodo (preferred_gateway_id) tras la v0.7 */}
          {links.length > 0 && (
            <div style={{ color: t.textFaint, fontSize: 11, paddingTop: 4 }}>
              Enrutado admin: automático (◆ primaria) — preferencias por nodo, próximamente
            </div>
          )}
        </BlockAccordion>

        <BlockAccordion id="insp.telemetry" title="Telemetría" icon="📈">
          {!lastTel && <div style={{ color: t.textFaint, fontSize: 12 }}>Sin telemetría registrada.</div>}
          {lastTel && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "0.5rem" }}>
              <Vital label="VOLTAJE" value={lastTel.voltage != null ? `${lastTel.voltage} V` : "—"} />
              <Vital label="USO CANAL" value={lastTel.channel_utilization != null ? `${lastTel.channel_utilization} %` : "—"} />
              <Vital label="AIR TX" value={lastTel.air_util_tx != null ? `${lastTel.air_util_tx} %` : "—"} />
              <Vital label="UPTIME" value={lastTel.uptime_seconds != null ? `${Math.round(lastTel.uptime_seconds / 3600)} h` : "—"} />
              <Vital label="RECIBIDA" value={relativeTime(lastTel.received_at)} />
              <Vital label="VÍA" value={lastTel.gateway_id ?? "—"} />
            </div>
          )}
        </BlockAccordion>

        <BlockAccordion id="insp.position" title="Posición" icon="📍">
          {!lastPos && (
            <div style={{ color: t.textFaint, fontSize: 12 }}>Sin posiciones registradas (sin GPS o aún sin difundir).</div>
          )}
          {lastPos && (
            <>
              <div
                onClick={() => copy(`${lastPos.latitude.toFixed(6)}, ${lastPos.longitude.toFixed(6)}`, "Coordenadas")}
                title="Copiar coordenadas"
                style={{ fontFamily: t.fontMono, fontSize: 12, cursor: "pointer" }}
              >
                {lastPos.latitude.toFixed(6)}, {lastPos.longitude.toFixed(6)} ⧉
              </div>
              <div style={{ color: t.textDim, fontSize: 11.5, fontFamily: t.fontMono, marginTop: 2 }}>
                {lastPos.altitude_m != null ? `${lastPos.altitude_m} m` : "— m"} ·{" "}
                {lastPos.sats_in_view != null ? `${lastPos.sats_in_view} sats` : "— sats"} ·{" "}
                {relativeTime(lastPos.received_at)}
              </div>
            </>
          )}
        </BlockAccordion>

        <BlockAccordion
          id="insp.operations"
          title="Operaciones"
          icon="⚙"
          count={nodeOps.filter((o) => !["succeeded", "succeeded_unconfirmed", "cancelled"].includes(o.status)).length}
          action={
            <button
              style={{ background: "none", border: "none", color: t.accent, cursor: "pointer", fontSize: 12, padding: 0 }}
              onClick={(e) => {
                e.stopPropagation();
                onGoTo("jobs");
              }}
            >
              Ver todas →
            </button>
          }
        >
          {nodeOps.length === 0 && <div style={{ color: t.textFaint, fontSize: 12 }}>Sin operaciones recientes.</div>}
          {nodeOps.map((op) => (
            <div key={op.id} style={{ display: "flex", alignItems: "baseline", gap: "0.45rem", padding: "0.16rem 0", fontSize: 12 }}>
              <span style={{ color: t.textFaint, fontFamily: t.fontMono, fontSize: 11 }}>#{op.id}</span>
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {op.operation_type}
                {typeof op.params.section === "string" ? `:${op.params.section}` : ""}
              </span>
              <span
                style={{ ...chipStyle(OP_STATUS_COLOR[op.status] ?? t.textDim), fontSize: 10.5 }}
                title={`estado técnico: ${op.status}`}
              >
                {OP_STATUS_LABEL[op.status] ?? op.status}
              </span>
              {RETRYABLE.has(op.status) && (
                <button style={iconBtn} title="Reintentar (re-evalúa la pasarela)" onClick={() => doRetry.mutate(op.id)}>
                  ↻
                </button>
              )}
            </div>
          ))}
        </BlockAccordion>

        <BlockAccordion id="insp.organization" title="Organización" icon="🏷" count={nodeTagIds.size + nodeGroupIds.size}>
          <div style={{ color: t.textFaint, fontSize: 10.5, letterSpacing: "0.06em", marginBottom: 3 }}>ETIQUETAS</div>
          <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", alignItems: "center", marginBottom: 8 }}>
            {(allTags.data ?? []).map((x) => {
              const has = nodeTagIds.has(x.id);
              return (
                <button
                  key={x.id}
                  style={{ ...chipStyle(has ? t.accent : t.textFaint), cursor: "pointer", fontSize: 11 }}
                  onClick={() => {
                    const next = new Set(nodeTagIds);
                    if (has) next.delete(x.id);
                    else next.add(x.id);
                    saveTags.mutate([...next]);
                  }}
                >
                  {x.name}
                </button>
              );
            })}
            <input
              style={inputStyle}
              placeholder="+ etiqueta"
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
          <div style={{ color: t.textFaint, fontSize: 10.5, letterSpacing: "0.06em", marginBottom: 3 }}>GRUPOS</div>
          <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", alignItems: "center" }}>
            {(allGroups.data ?? []).map((g) => {
              const member = nodeGroupIds.has(g.id);
              return (
                <button
                  key={g.id}
                  style={{ ...chipStyle(member ? t.accent : t.textFaint), cursor: "pointer", fontSize: 11 }}
                  onClick={() => membership.mutate({ groupId: g.id, member: !member })}
                  title={`${g.member_count} nodos`}
                >
                  {g.name}
                </button>
              );
            })}
            <input
              style={inputStyle}
              placeholder="+ grupo"
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
        </BlockAccordion>

        <BlockAccordion id="insp.remote" title="Remoto (NodeDB del nodo)" icon="📡">
          <RemoteFlags nodeId={nodeId} subjectOptions={subjectOptions} />
        </BlockAccordion>
      </div>
    </aside>
  );
}

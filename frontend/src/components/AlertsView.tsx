import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  ackAlert,
  createChannel,
  deleteChannel,
  fetchAlertRules,
  fetchAlerts,
  fetchChannels,
  fetchNodes,
  patchAlertRule,
  testChannel,
  type AlertOut,
  type Severity,
} from "../api/client";
import { scopeAlertsToGroup, useGroupNodeIds } from "../context/GroupContext";
import { relativeTime } from "../time";
import { GroupScopeBanner } from "./shell/GroupScopeBanner";

/**
 * Alertas (identidad v0.8): un puesto de triaje, no una página de tablas.
 * Columna principal = bandeja activa con gutter de severidad y ACK a un
 * clic (endpoint de 3C); debajo, historial compacto. Columna derecha =
 * reglas y canales como paneles de configuración del motor.
 */

const SEV_COLOR: Record<Severity, string> = {
  INFO: "var(--text-dim)",
  WARNING: "var(--warn)",
  CRITICAL: "var(--crit)",
};

function AlertRow({
  alert,
  onAck,
  onOpenNode,
  outOfGroup,
}: {
  alert: AlertOut;
  onAck?: (id: number) => void;
  onOpenNode?: (nodeId: string) => void;
  outOfGroup?: boolean;
}) {
  const color = SEV_COLOR[alert.severity];
  const resolved = alert.status === "resolved";
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        gap: "0.6rem",
        padding: "0.4rem 0.75rem",
        borderBottom: "1px solid var(--border-subtle)",
        borderLeft: `2px solid ${resolved ? "var(--border)" : color}`,
        opacity: resolved ? 0.65 : 1,
        fontSize: 12,
      }}
    >
      <span className="mono" style={{ color, fontSize: 10.5, minWidth: 60 }}>
        {alert.severity}
      </span>
      <span style={{ flex: 1, minWidth: 0 }}>
        <span style={{ color: "var(--text)" }}>{alert.message}</span>{" "}
        <span style={{ color: "var(--text-faint)" }}>· {alert.rule_name}</span>
        {outOfGroup && (
          <span
            className="chip"
            style={{ marginLeft: 6, color: "var(--warn)", borderColor: "var(--warn)" }}
            title="Nodo fuera del grupo activo — visible por ser CRITICAL"
          >
            ⤫ fuera del grupo
          </span>
        )}
      </span>
      <span className="mono" style={{ color: "var(--text-faint)", fontSize: 10.5, whiteSpace: "nowrap" }}>
        {resolved ? `resuelta ${relativeTime(alert.resolved_at)}` : relativeTime(alert.fired_at)}
      </span>
      {!resolved && alert.status === "acknowledged" && (
        <span className="chip" title={`Reconocida ${relativeTime(alert.acknowledged_at)}`}>ACK</span>
      )}
      {!resolved && alert.status === "firing" && onAck && (
        <button className="btn ghost" style={{ padding: "0.1rem 0.5rem", fontSize: 11 }} onClick={() => onAck(alert.id)}>
          ACK
        </button>
      )}
      {alert.subject_type === "node" && onOpenNode && (
        <button
          className="btn ghost"
          style={{ padding: "0.1rem 0.5rem", fontSize: 11 }}
          title="Abrir el nodo en el Inspector"
          onClick={() => onOpenNode(alert.subject_id)}
        >
          →
        </button>
      )}
    </div>
  );
}

export function AlertsView({ onOpenNode }: { onOpenNode?: (nodeId: string) => void }) {
  const queryClient = useQueryClient();
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["alerts"] });
    queryClient.invalidateQueries({ queryKey: ["alert-rules"] });
    queryClient.invalidateQueries({ queryKey: ["channels"] });
  };

  const alerts = useQuery({ queryKey: ["alerts"], queryFn: () => fetchAlerts(undefined, 100), refetchInterval: 30_000 });
  const rules = useQuery({ queryKey: ["alert-rules"], queryFn: fetchAlertRules });
  const channels = useQuery({ queryKey: ["channels"], queryFn: fetchChannels });
  // Mismo queryKey que App.tsx/GroupContext: caché compartida, sin fetch nuevo.
  const nodes = useQuery({ queryKey: ["nodes"], queryFn: () => fetchNodes() });
  const groupNodeIds = useGroupNodeIds(nodes.data ?? []);

  const doAck = useMutation({ mutationFn: ackAlert, onSettled: invalidate });
  const toggleRule = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => patchAlertRule(id, { enabled }),
    onSettled: invalidate,
  });
  const addChannel = useMutation({ mutationFn: createChannel, onSettled: invalidate });
  const removeChannel = useMutation({ mutationFn: deleteChannel, onSettled: invalidate });
  const test = useMutation({ mutationFn: testChannel });

  const [chName, setChName] = useState("");
  const [chType, setChType] = useState<"webhook" | "ntfy">("ntfy");
  const [chTarget, setChTarget] = useState("");

  const all = alerts.data ?? [];
  const allActive = all.filter((a) => a.status !== "resolved");

  // Grupo activo: mismo criterio compartido con StatusPanel (GroupContext) —
  // nunca se duplica aquí.
  const { inScope: active, outOfGroupCritical } = useMemo(
    () => scopeAlertsToGroup(allActive, groupNodeIds),
    [allActive, groupNodeIds],
  );
  const isOutOfGroupCritical = (a: AlertOut) => outOfGroupCritical.has(a.id);
  const firing = active.filter((a) => a.status === "firing");
  const resolved = useMemo(
    () => scopeAlertsToGroup(all, groupNodeIds).inScope.filter((a) => a.status === "resolved").slice(0, 30),
    [all, groupNodeIds],
  );
  const critCount = active.filter((a) => a.severity === "CRITICAL").length;

  return (
    <div className="ws">
      <GroupScopeBanner shown={active.length} total={allActive.length} label="alertas" />
      <div className="kpis">
        <div className="kpi">
          <div className="v" style={{ color: critCount > 0 ? "var(--crit)" : "var(--text)" }}>{critCount}</div>
          <div className="k">Críticas</div>
        </div>
        <div className="kpi">
          <div className="v" style={{ color: active.length > 0 ? "var(--warn)" : "var(--text)" }}>{active.length}</div>
          <div className="k">Activas</div>
        </div>
        <div className="kpi">
          <div className="v">{firing.length}</div>
          <div className="k">Sin reconocer</div>
        </div>
        <div className="kpi">
          <div className="v" style={{ color: "var(--text-dim)" }}>{(rules.data ?? []).filter((r) => r.enabled).length}/{(rules.data ?? []).length}</div>
          <div className="k">Reglas activas</div>
        </div>
        <div className="kpi">
          <div className="v" style={{ color: "var(--text-dim)" }}>{(channels.data ?? []).length}</div>
          <div className="k">Canales</div>
        </div>
      </div>

      <div className="ws-cols">
        {/* Columna principal: triaje */}
        <div style={{ flex: 2, minWidth: 0, display: "flex", flexDirection: "column", gap: 1 }}>
          <div className="panel" style={{ flex: 2 }}>
            <div className="panel-head">
              <span className="panel-title">Bandeja activa</span>
              <span className="panel-count">{active.length} alertas</span>
            </div>
            <div className="panel-body flush">
              {alerts.isLoading && <div className="empty">Cargando…</div>}
              {!alerts.isLoading && active.length === 0 && (
                <div className="empty">Sin alertas activas — red dentro de los umbrales.</div>
              )}
              {active.map((a) => (
                <AlertRow
                  key={a.id}
                  alert={a}
                  onAck={(id) => doAck.mutate(id)}
                  onOpenNode={onOpenNode}
                  outOfGroup={isOutOfGroupCritical(a)}
                />
              ))}
            </div>
          </div>
          <div className="panel" style={{ flex: 1 }}>
            <div className="panel-head">
              <span className="panel-title">Historial</span>
              <span className="panel-count">últimas {resolved.length}</span>
            </div>
            <div className="panel-body flush">
              {resolved.length === 0 && <div className="empty">Sin alertas resueltas todavía.</div>}
              {resolved.map((a) => (
                <AlertRow key={a.id} alert={a} onOpenNode={onOpenNode} />
              ))}
            </div>
          </div>
        </div>

        {/* Columna derecha: el motor */}
        <div style={{ flex: 1, minWidth: 300, maxWidth: 420, display: "flex", flexDirection: "column", gap: 1 }}>
          <div className="panel" style={{ flex: 1 }}>
            <div className="panel-head">
              <span className="panel-title">Reglas</span>
              <span className="panel-count">{(rules.data ?? []).length}</span>
            </div>
            <div className="panel-body flush">
              {(rules.data ?? []).map((r) => (
                <label
                  key={r.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.6rem",
                    padding: "0.4rem 0.75rem",
                    borderBottom: "1px solid var(--border-subtle)",
                    cursor: "pointer",
                    fontSize: 12,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={r.enabled}
                    onChange={(e) => toggleRule.mutate({ id: r.id, enabled: e.target.checked })}
                  />
                  <span className="mono" style={{ color: SEV_COLOR[r.severity], fontSize: 10, minWidth: 60 }}>
                    {r.severity}
                  </span>
                  <span style={{ color: r.enabled ? "var(--text)" : "var(--text-faint)" }}>{r.name}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="panel" style={{ flex: 1 }}>
            <div className="panel-head">
              <span className="panel-title">Canales de notificación</span>
              <span className="panel-count">{(channels.data ?? []).length}</span>
            </div>
            <div className="panel-body">
              {(channels.data ?? []).length === 0 && (
                <p style={{ color: "var(--text-faint)", fontSize: 12, marginTop: 0 }}>
                  Sin canales. Las alertas solo se verán en el NOC.
                </p>
              )}
              {(channels.data ?? []).map((c) => (
                <div key={c.id} style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.4rem", fontSize: 12 }}>
                  <span className="mono">{c.name}</span>
                  <span className="chip">{c.channel_type}</span>
                  <span style={{ marginLeft: "auto", display: "flex", gap: "0.3rem" }}>
                    <button className="btn ghost" style={{ fontSize: 11 }} onClick={() => test.mutate(c.id)}>Probar</button>
                    <button className="btn ghost" style={{ fontSize: 11 }} onClick={() => removeChannel.mutate(c.id)}>✕</button>
                  </span>
                </div>
              ))}
              {test.isSuccess && <p style={{ color: "var(--ok)", fontSize: 12 }}>Mensaje de prueba enviado.</p>}
              {test.isError && <p style={{ color: "var(--crit)", fontSize: 12 }}>{String(test.error)}</p>}

              <div className="microlabel" style={{ margin: "0.8rem 0 0.4rem" }}>Añadir canal</div>
              <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                <input className="input" style={{ width: 110 }} placeholder="Nombre" value={chName} onChange={(e) => setChName(e.target.value)} />
                <select className="input" value={chType} onChange={(e) => setChType(e.target.value as "webhook" | "ntfy")}>
                  <option value="ntfy">ntfy</option>
                  <option value="webhook">webhook</option>
                </select>
                <input
                  className="input"
                  style={{ flex: 1, minWidth: 160 }}
                  placeholder={chType === "ntfy" ? "topic (p. ej. meshtastic-noc)" : "URL del webhook"}
                  value={chTarget}
                  onChange={(e) => setChTarget(e.target.value)}
                />
                <button
                  className="btn"
                  disabled={!chName || !chTarget}
                  onClick={() => {
                    addChannel.mutate({
                      name: chName,
                      channel_type: chType,
                      enabled: true,
                      config: chType === "ntfy" ? { topic: chTarget } : { url: chTarget },
                    });
                    setChName("");
                    setChTarget("");
                  }}
                >
                  Crear
                </button>
              </div>
              {addChannel.isError && <p style={{ color: "var(--crit)", fontSize: 12 }}>{String(addChannel.error)}</p>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

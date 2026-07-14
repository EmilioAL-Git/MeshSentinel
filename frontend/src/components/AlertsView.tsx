import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  ackAlert,
  createAlertRule,
  createChannel,
  deleteAlertRule,
  deleteChannel,
  fetchAlertRules,
  fetchAlerts,
  fetchChannels,
  fetchNodes,
  patchAlertRule,
  patchChannel,
  testChannel,
  type AlertOut,
  type AlertRuleOut,
  type ChannelOut,
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

// Cada rule_type usa threshold y/o duration_seconds con un significado
// distinto (evaluators.py) — la etiqueta y unidad se adaptan por tipo.
const RULE_FIELD_META: Record<
  string,
  {
    label: string;
    threshold?: { label: string; step?: number; default: number };
    duration?: { label: string; toUi: (s: number) => number; fromUi: (v: number) => number; default: number };
  }
> = {
  low_battery: { label: "Batería baja", threshold: { label: "% batería", default: 20 } },
  snr_degraded: { label: "SNR degradado", threshold: { label: "SNR (dB)", step: 0.5, default: 0 } },
  node_offline: {
    label: "Nodo sin actividad",
    duration: { label: "Minutos sin actividad", toUi: (s) => Math.round(s / 60), fromUi: (m) => m * 60, default: 15 },
  },
  gateway_disconnected: {
    label: "Pasarela desconectada",
    duration: { label: "Segundos sin heartbeat", toUi: (s) => s, fromUi: (s) => s, default: 120 },
  },
};

function RuleEditor({ rule, onSave, onCancel }: { rule: AlertRuleOut; onSave: (changes: Partial<AlertRuleOut>) => void; onCancel: () => void }) {
  const meta = RULE_FIELD_META[rule.rule_type];
  const [severity, setSeverity] = useState<Severity>(rule.severity);
  const [threshold, setThreshold] = useState(rule.threshold ?? 0);
  const [durationUi, setDurationUi] = useState(meta?.duration ? meta.duration.toUi(rule.duration_seconds ?? 0) : 0);
  const [cooldown, setCooldown] = useState(rule.cooldown_seconds);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.4rem",
        padding: "0.5rem 0.75rem 0.7rem",
        borderBottom: "1px solid var(--border-subtle)",
        background: "var(--surface-2, rgba(255,255,255,0.03))",
        fontSize: 12,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <span className="microlabel" style={{ minWidth: 70 }}>Severidad</span>
        <select className="input" value={severity} onChange={(e) => setSeverity(e.target.value as Severity)}>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="CRITICAL">CRITICAL</option>
        </select>
      </div>
      {meta?.threshold && (
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <span className="microlabel" style={{ minWidth: 70 }}>{meta.threshold.label}</span>
          <input
            className="input"
            type="number"
            step={meta.threshold.step ?? 1}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
          />
        </div>
      )}
      {meta?.duration && (
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <span className="microlabel" style={{ minWidth: 70 }}>{meta.duration.label}</span>
          <input className="input" type="number" min={1} value={durationUi} onChange={(e) => setDurationUi(Number(e.target.value))} />
        </div>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <span className="microlabel" style={{ minWidth: 70 }}>Enfriamiento (s)</span>
        <input className="input" type="number" min={0} value={cooldown} onChange={(e) => setCooldown(Number(e.target.value))} />
      </div>
      <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.2rem" }}>
        <button
          className="btn"
          style={{ fontSize: 11 }}
          onClick={() =>
            onSave({
              severity,
              threshold: meta?.threshold ? threshold : rule.threshold,
              duration_seconds: meta?.duration ? meta.duration.fromUi(durationUi) : rule.duration_seconds,
              cooldown_seconds: cooldown,
            })
          }
        >
          Guardar
        </button>
        <button className="btn ghost" style={{ fontSize: 11 }} onClick={onCancel}>
          Cancelar
        </button>
      </div>
    </div>
  );
}

function NewRuleForm({ onSave, onCancel }: { onSave: (rule: Omit<AlertRuleOut, "id">) => void; onCancel: () => void }) {
  const [ruleType, setRuleType] = useState<keyof typeof RULE_FIELD_META>("low_battery");
  const [name, setName] = useState(RULE_FIELD_META.low_battery.label);
  const [severity, setSeverity] = useState<Severity>("WARNING");
  const meta = RULE_FIELD_META[ruleType];
  const [threshold, setThreshold] = useState(meta.threshold?.default ?? 0);
  const [durationUi, setDurationUi] = useState(meta.duration?.default ?? 0);
  const [cooldown, setCooldown] = useState(0);

  const changeType = (t: keyof typeof RULE_FIELD_META) => {
    setRuleType(t);
    setName(RULE_FIELD_META[t].label);
    setThreshold(RULE_FIELD_META[t].threshold?.default ?? 0);
    setDurationUi(RULE_FIELD_META[t].duration?.default ?? 0);
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.4rem",
        padding: "0.5rem 0.75rem 0.7rem",
        borderBottom: "1px solid var(--border-subtle)",
        background: "var(--surface-2, rgba(255,255,255,0.03))",
        fontSize: 12,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <span className="microlabel" style={{ minWidth: 70 }}>Tipo</span>
        <select className="input" value={ruleType} onChange={(e) => changeType(e.target.value as keyof typeof RULE_FIELD_META)}>
          {Object.entries(RULE_FIELD_META).map(([type, m]) => (
            <option key={type} value={type}>{m.label}</option>
          ))}
        </select>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <span className="microlabel" style={{ minWidth: 70 }}>Nombre</span>
        <input className="input" style={{ flex: 1 }} value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <span className="microlabel" style={{ minWidth: 70 }}>Severidad</span>
        <select className="input" value={severity} onChange={(e) => setSeverity(e.target.value as Severity)}>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="CRITICAL">CRITICAL</option>
        </select>
      </div>
      {meta.threshold && (
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <span className="microlabel" style={{ minWidth: 70 }}>{meta.threshold.label}</span>
          <input
            className="input"
            type="number"
            step={meta.threshold.step ?? 1}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
          />
        </div>
      )}
      {meta.duration && (
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <span className="microlabel" style={{ minWidth: 70 }}>{meta.duration.label}</span>
          <input className="input" type="number" min={1} value={durationUi} onChange={(e) => setDurationUi(Number(e.target.value))} />
        </div>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <span className="microlabel" style={{ minWidth: 70 }}>Enfriamiento (s)</span>
        <input className="input" type="number" min={0} value={cooldown} onChange={(e) => setCooldown(Number(e.target.value))} />
      </div>
      <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.2rem" }}>
        <button
          className="btn"
          disabled={!name.trim()}
          style={{ fontSize: 11 }}
          onClick={() =>
            onSave({
              name: name.trim(),
              rule_type: ruleType,
              severity,
              enabled: true,
              threshold: meta.threshold ? threshold : null,
              duration_seconds: meta.duration ? meta.duration.fromUi(durationUi) : null,
              cooldown_seconds: cooldown,
              params: {},
            })
          }
        >
          Crear regla
        </button>
        <button className="btn ghost" style={{ fontSize: 11 }} onClick={onCancel}>
          Cancelar
        </button>
      </div>
    </div>
  );
}

// ntfy guarda el destino en config.topic, webhook en config.url.
function channelTarget(c: ChannelOut): string {
  return c.channel_type === "ntfy" ? String(c.config.topic ?? "") : String(c.config.url ?? "");
}

function ChannelEditor({ channel, onSave, onCancel }: { channel: ChannelOut; onSave: (changes: Partial<ChannelOut>) => void; onCancel: () => void }) {
  const [name, setName] = useState(channel.name);
  const [target, setTarget] = useState(channelTarget(channel));

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.4rem",
        padding: "0.5rem 0.75rem 0.7rem",
        borderBottom: "1px solid var(--border-subtle)",
        background: "var(--surface-2, rgba(255,255,255,0.03))",
        fontSize: 12,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <span className="microlabel" style={{ minWidth: 70 }}>Nombre</span>
        <input className="input" style={{ flex: 1 }} value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <span className="microlabel" style={{ minWidth: 70 }}>{channel.channel_type === "ntfy" ? "Topic" : "URL"}</span>
        <input className="input" style={{ flex: 1 }} value={target} onChange={(e) => setTarget(e.target.value)} />
      </div>
      <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.2rem" }}>
        <button
          className="btn"
          disabled={!name.trim() || !target.trim()}
          style={{ fontSize: 11 }}
          onClick={() =>
            onSave({
              name: name.trim(),
              config: channel.channel_type === "ntfy" ? { topic: target.trim() } : { url: target.trim() },
            })
          }
        >
          Guardar
        </button>
        <button className="btn ghost" style={{ fontSize: 11 }} onClick={onCancel}>
          Cancelar
        </button>
      </div>
    </div>
  );
}

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
  const editRule = useMutation({
    mutationFn: ({ id, changes }: { id: number; changes: Partial<AlertRuleOut> }) => patchAlertRule(id, changes),
    onSettled: invalidate,
  });
  const newRule = useMutation({ mutationFn: createAlertRule, onSettled: invalidate });
  const removeRule = useMutation({ mutationFn: deleteAlertRule, onSettled: invalidate });
  const [editingRuleId, setEditingRuleId] = useState<number | null>(null);
  const [creatingRule, setCreatingRule] = useState(false);
  const addChannel = useMutation({ mutationFn: createChannel, onSettled: invalidate });
  const editChannel = useMutation({
    mutationFn: ({ id, changes }: { id: number; changes: Partial<ChannelOut> }) => patchChannel(id, changes),
    onSettled: invalidate,
  });
  const removeChannel = useMutation({ mutationFn: deleteChannel, onSettled: invalidate });
  const test = useMutation({ mutationFn: testChannel });
  const [editingChannelId, setEditingChannelId] = useState<number | null>(null);

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
              <button
                className="btn ghost"
                style={{ marginLeft: "auto", padding: "0.1rem 0.5rem", fontSize: 11 }}
                onClick={() => {
                  setCreatingRule((v) => !v);
                  setEditingRuleId(null);
                }}
              >
                {creatingRule ? "▲" : "+ Nueva"}
              </button>
            </div>
            <div className="panel-body flush">
              {creatingRule && (
                <NewRuleForm
                  onCancel={() => setCreatingRule(false)}
                  onSave={(rule) => {
                    newRule.mutate(rule);
                    setCreatingRule(false);
                  }}
                />
              )}
              {(rules.data ?? []).map((r) => (
                <div key={r.id}>
                  <label
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "0.6rem",
                      padding: "0.4rem 0.75rem",
                      borderBottom: editingRuleId === r.id ? "none" : "1px solid var(--border-subtle)",
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
                    <span style={{ color: r.enabled ? "var(--text)" : "var(--text-faint)", flex: 1 }}>{r.name}</span>
                    <button
                      className="btn ghost"
                      style={{ padding: "0.1rem 0.5rem", fontSize: 11 }}
                      onClick={(e) => {
                        e.preventDefault();
                        setEditingRuleId(editingRuleId === r.id ? null : r.id);
                        setCreatingRule(false);
                      }}
                    >
                      {editingRuleId === r.id ? "▲" : "Ajustar"}
                    </button>
                    <button
                      className="btn ghost"
                      style={{ padding: "0.1rem 0.5rem", fontSize: 11 }}
                      title="Borrar regla"
                      onClick={(e) => {
                        e.preventDefault();
                        if (window.confirm(`¿Borrar la regla «${r.name}»?`)) removeRule.mutate(r.id);
                      }}
                    >
                      ✕
                    </button>
                  </label>
                  {editingRuleId === r.id && (
                    <RuleEditor
                      rule={r}
                      onCancel={() => setEditingRuleId(null)}
                      onSave={(changes) => {
                        editRule.mutate({ id: r.id, changes });
                        setEditingRuleId(null);
                      }}
                    />
                  )}
                </div>
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
                <div key={c.id} style={{ marginBottom: "0.4rem" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: 12 }}>
                    <input
                      type="checkbox"
                      checked={c.enabled}
                      title={c.enabled ? "Canal activo" : "Canal desactivado"}
                      onChange={(e) => editChannel.mutate({ id: c.id, changes: { enabled: e.target.checked } })}
                    />
                    <span className="mono" style={{ color: c.enabled ? "var(--text)" : "var(--text-faint)" }}>{c.name}</span>
                    <span className="chip">{c.channel_type}</span>
                    <span style={{ marginLeft: "auto", display: "flex", gap: "0.3rem" }}>
                      <button className="btn ghost" style={{ fontSize: 11 }} onClick={() => test.mutate(c.id)}>Probar</button>
                      <button
                        className="btn ghost"
                        style={{ fontSize: 11 }}
                        onClick={() => setEditingChannelId(editingChannelId === c.id ? null : c.id)}
                      >
                        {editingChannelId === c.id ? "▲" : "Editar"}
                      </button>
                      <button
                        className="btn ghost"
                        style={{ fontSize: 11 }}
                        onClick={() => {
                          if (window.confirm(`¿Borrar el canal «${c.name}»?`)) removeChannel.mutate(c.id);
                        }}
                      >
                        ✕
                      </button>
                    </span>
                  </div>
                  {editingChannelId === c.id && (
                    <ChannelEditor
                      channel={c}
                      onCancel={() => setEditingChannelId(null)}
                      onSave={(changes) => {
                        editChannel.mutate({ id: c.id, changes });
                        setEditingChannelId(null);
                      }}
                    />
                  )}
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

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  ackAlert,
  createAlertRule,
  createChannel,
  createProvider,
  deleteAlertRule,
  deleteChannel,
  deleteProvider,
  displayName,
  duplicateProvider,
  fetchAlertRules,
  fetchAlerts,
  fetchChannels,
  fetchGroups,
  fetchNodes,
  fetchProviders,
  patchAlertRule,
  patchChannel,
  patchProvider,
  testProvider,
  type AlertOut,
  type AlertRuleOut,
  type ChannelOut,
  type ProviderOut,
  type Severity,
} from "../api/client";
import { scopeAlertsToGroup, useGroupNodeIds } from "../context/GroupContext";
import { relativeTime } from "../time";
import { useUrlString } from "../hooks/useUrlState";
import { GroupScopeBanner } from "./shell/GroupScopeBanner";
import { Modal } from "./shell/Modal";

/**
 * Alertas (identidad v0.8): un puesto de triaje, no una página de tablas.
 * Columna principal = bandeja activa con gutter de severidad y ACK a un
 * clic (endpoint de 3C); debajo, historial compacto. Columna derecha =
 * reglas, integraciones y canales como paneles de configuración del motor.
 *
 * Vocabulario (backend ⇄ UI, notificaciones multi-proveedor): una
 * "Integración" es la instancia de proveedor configurada (un webhook
 * concreto, un bot de Telegram concreto — backend: notification_providers).
 * Un "Canal" es la agrupación lógica a la que apuntan las reglas
 * (p.ej. "Operadores", "Guardia" — backend: notification_channels), y
 * agrupa 1+ integraciones. Una regla sin canales asignados difunde a todas
 * las integraciones activas (comportamiento por defecto, sin cambios).
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
  gateway_no_traffic: {
    label: "Pasarela sin tráfico",
    duration: { label: "Minutos sin oír a la malla", toUi: (s) => Math.round(s / 60), fromUi: (m) => m * 60, default: 30 },
  },
  low_redundancy: { label: "Redundancia baja", threshold: { label: "% mínimo con 2+ pasarelas", default: 50 } },
  temperature_high: { label: "Temperatura alta", threshold: { label: "°C máximos", step: 0.5, default: 45 } },
  channel_utilization_high: { label: "Canal saturado", threshold: { label: "% utilización máx.", default: 25 } },
  position_lost: {
    label: "Posición perdida",
    duration: { label: "Minutos sin posición (nodo activo)", toUi: (s) => Math.round(s / 60), fromUi: (m) => m * 60, default: 120 },
  },
  neighbor_link_lost: {
    label: "Enlace de vecinos perdido",
    duration: { label: "Minutos sin reoír el enlace", toUi: (s) => Math.round(s / 60), fromUi: (m) => m * 60, default: 120 },
  },
};

// Tipos cuyo sujeto son pasarelas: sin escopado por grupo (la API lo rechaza)
const GROUP_UNSUPPORTED = new Set(["gateway_disconnected", "gateway_no_traffic"]);

// Metadatos por tipo de proveedor: qué campos pide su `configuration`, sin
// lógica if/else dispersa por el resto del componente (mismo patrón que
// RULE_FIELD_META). Añadir un proveedor nuevo aquí = ya aparece en el
// formulario de "+ Nueva integración".
const PROVIDER_FIELD_META: Record<
  string,
  {
    label: string;
    fields: { key: string; label: string; type?: "text" | "password"; placeholder?: string; optional?: boolean }[];
  }
> = {
  webhook: {
    label: "Webhook",
    fields: [{ key: "url", label: "URL", placeholder: "https://ejemplo.com/hook" }],
  },
  ntfy: {
    label: "ntfy",
    fields: [
      { key: "topic", label: "Topic", placeholder: "meshtastic-noc" },
      { key: "url", label: "Servidor", placeholder: "https://ntfy.sh (opcional)", optional: true },
      { key: "token", label: "Token", type: "password", optional: true },
    ],
  },
  telegram: {
    label: "Telegram",
    fields: [
      { key: "bot_token", label: "Bot Token", type: "password" },
      { key: "chat_id", label: "Chat ID" },
    ],
  },
};

function ChannelPicker({
  channels,
  selected,
  onChange,
}: {
  channels: ChannelOut[];
  selected: number[];
  onChange: (ids: number[]) => void;
}) {
  const toggle = (id: number) =>
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
      <span className="microlabel">Canales</span>
      {channels.length === 0 && (
        <span style={{ color: "var(--text-faint)", fontSize: 11 }}>
          Sin canales creados — todas las integraciones activas (por defecto).
        </span>
      )}
      {channels.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
          {channels.map((c) => (
            <label key={c.id} style={{ display: "flex", alignItems: "center", gap: "0.3rem", fontSize: 11.5 }}>
              <input type="checkbox" checked={selected.includes(c.id)} onChange={() => toggle(c.id)} />
              {c.name}
            </label>
          ))}
        </div>
      )}
      {selected.length === 0 && channels.length > 0 && (
        <span style={{ color: "var(--text-faint)", fontSize: 11 }}>
          Ninguno seleccionado = todas las integraciones activas (por defecto).
        </span>
      )}
    </div>
  );
}

function RuleEditor({
  rule,
  channels,
  onSave,
  onCancel,
}: {
  rule: AlertRuleOut;
  channels: ChannelOut[];
  onSave: (changes: Partial<AlertRuleOut>) => void;
  onCancel: () => void;
}) {
  const meta = RULE_FIELD_META[rule.rule_type];
  const [severity, setSeverity] = useState<Severity>(rule.severity);
  const [threshold, setThreshold] = useState(rule.threshold ?? 0);
  const [durationUi, setDurationUi] = useState(meta?.duration ? meta.duration.toUi(rule.duration_seconds ?? 0) : 0);
  const [cooldown, setCooldown] = useState(rule.cooldown_seconds);
  const [channelIds, setChannelIds] = useState<number[]>(rule.channel_ids ?? []);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.4rem",
        padding: "0.5rem 0.75rem 0.7rem",
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
      <ChannelPicker channels={channels} selected={channelIds} onChange={setChannelIds} />
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
              channel_ids: channelIds,
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

function NewRuleForm({
  channels,
  onSave,
  onCancel,
}: {
  channels: ChannelOut[];
  onSave: (rule: Omit<AlertRuleOut, "id">) => void;
  onCancel: () => void;
}) {
  const [ruleType, setRuleType] = useState<keyof typeof RULE_FIELD_META>("low_battery");
  const [name, setName] = useState(RULE_FIELD_META.low_battery.label);
  const [severity, setSeverity] = useState<Severity>("WARNING");
  const meta = RULE_FIELD_META[ruleType];
  const [threshold, setThreshold] = useState(meta.threshold?.default ?? 0);
  const [durationUi, setDurationUi] = useState(meta.duration?.default ?? 0);
  const [cooldown, setCooldown] = useState(0);
  const [channelIds, setChannelIds] = useState<number[]>([]);
  // Ámbito de la regla (§1.3, ampliado): toda la red / un grupo / un nodo
  // concreto, mutuamente excluyentes. El nombre por defecto incorpora el
  // ámbito — `name` es UNIQUE en BD y colisionaría con la regla global
  // sembrada del mismo tipo.
  const [scopeKind, setScopeKind] = useState<"all" | "group" | "node">("all");
  const [groupId, setGroupId] = useState<number | null>(null);
  const [nodeId, setNodeId] = useState<string | null>(null);
  const groups = useQuery({ queryKey: ["groups"], queryFn: fetchGroups });
  const nodes = useQuery({ queryKey: ["nodes"], queryFn: () => fetchNodes() });

  const defaultName = (t: keyof typeof RULE_FIELD_META, kind: "all" | "group" | "node", gid: number | null, nid: string | null) => {
    const base = RULE_FIELD_META[t].label;
    if (kind === "group") {
      const group = (groups.data ?? []).find((g) => g.id === gid);
      return group ? `${base} · ${group.name}` : base;
    }
    if (kind === "node") {
      const node = (nodes.data ?? []).find((n) => n.node.node_id === nid);
      return node ? `${base} · ${displayName(node.node)}` : base;
    }
    return base;
  };

  const changeType = (t: keyof typeof RULE_FIELD_META) => {
    setRuleType(t);
    const kind = GROUP_UNSUPPORTED.has(t) ? "all" : scopeKind;
    if (GROUP_UNSUPPORTED.has(t)) {
      setScopeKind("all");
      setGroupId(null);
      setNodeId(null);
    }
    setName(defaultName(t, kind, groupId, nodeId));
    setThreshold(RULE_FIELD_META[t].threshold?.default ?? 0);
    setDurationUi(RULE_FIELD_META[t].duration?.default ?? 0);
  };

  const changeScopeKind = (kind: "all" | "group" | "node") => {
    // Si el nombre sigue siendo el autogenerado, se regenera con el ámbito nuevo
    if (name === defaultName(ruleType, scopeKind, groupId, nodeId)) setName(defaultName(ruleType, kind, null, null));
    setScopeKind(kind);
    setGroupId(null);
    setNodeId(null);
  };

  const changeGroup = (gid: number | null) => {
    if (name === defaultName(ruleType, scopeKind, groupId, nodeId)) setName(defaultName(ruleType, "group", gid, null));
    setGroupId(gid);
  };

  const changeNode = (nid: string | null) => {
    if (name === defaultName(ruleType, scopeKind, groupId, nodeId)) setName(defaultName(ruleType, "node", null, nid));
    setNodeId(nid);
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.4rem",
        padding: "0.5rem 0.75rem 0.7rem",
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
      {!GROUP_UNSUPPORTED.has(ruleType) && (
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", minWidth: 0 }}>
          <span className="microlabel" style={{ minWidth: 70, flexShrink: 0 }}>Ámbito</span>
          <select
            className="input"
            style={{ flexShrink: 0 }}
            value={scopeKind}
            onChange={(e) => changeScopeKind(e.target.value as "all" | "group" | "node")}
          >
            <option value="all">Toda la red</option>
            <option value="group">Un grupo</option>
            <option value="node">Un nodo</option>
          </select>
          {scopeKind === "group" && (
            <select
              className="input"
              style={{ flex: 1, minWidth: 0, width: 0 }}
              value={groupId ?? ""}
              onChange={(e) => changeGroup(e.target.value === "" ? null : Number(e.target.value))}
            >
              <option value="" disabled>Elegir grupo…</option>
              {(groups.data ?? []).map((g) => (
                <option key={g.id} value={g.id}>{g.name}</option>
              ))}
            </select>
          )}
          {scopeKind === "node" && (
            <select
              className="input"
              style={{ flex: 1, minWidth: 0, width: 0 }}
              value={nodeId ?? ""}
              onChange={(e) => changeNode(e.target.value === "" ? null : e.target.value)}
            >
              <option value="" disabled>Elegir nodo…</option>
              {(nodes.data ?? []).map((n) => (
                <option key={n.node.node_id} value={n.node.node_id}>{displayName(n.node)}</option>
              ))}
            </select>
          )}
        </div>
      )}
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
      <ChannelPicker channels={channels} selected={channelIds} onChange={setChannelIds} />
      <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.2rem" }}>
        <button
          className="btn"
          disabled={!name.trim() || (scopeKind === "group" && groupId == null) || (scopeKind === "node" && nodeId == null)}
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
              group_id: scopeKind === "group" ? groupId : null,
              node_id: scopeKind === "node" ? nodeId : null,
              channel_ids: channelIds,
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

function ProviderFieldsEditor({
  providerType,
  configuration,
  onChange,
}: {
  providerType: string;
  configuration: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
}) {
  const meta = PROVIDER_FIELD_META[providerType];
  if (!meta) return null;
  return (
    <>
      {meta.fields.map((f) => (
        <div key={f.key} style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <span className="microlabel" style={{ minWidth: 70 }}>{f.label}</span>
          <input
            className="input"
            style={{ flex: 1 }}
            type={f.type === "password" ? "password" : "text"}
            placeholder={f.placeholder}
            value={String(configuration[f.key] ?? "")}
            onChange={(e) => onChange({ ...configuration, [f.key]: e.target.value })}
          />
        </div>
      ))}
    </>
  );
}

function ProviderEditor({
  provider,
  onSave,
  onCancel,
}: {
  provider: ProviderOut;
  onSave: (changes: { name: string; configuration: Record<string, unknown> }) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(provider.name);
  const [configuration, setConfiguration] = useState<Record<string, unknown>>(provider.configuration);
  const meta = PROVIDER_FIELD_META[provider.provider];
  const requiredOk = (meta?.fields ?? []).every((f) => f.optional || String(configuration[f.key] ?? "").trim());

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.4rem",
        padding: "0.5rem 0.75rem 0.7rem",
        fontSize: 12,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <span className="microlabel" style={{ minWidth: 70 }}>Nombre</span>
        <input className="input" style={{ flex: 1 }} value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <ProviderFieldsEditor providerType={provider.provider} configuration={configuration} onChange={setConfiguration} />
      <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.2rem" }}>
        <button
          className="btn"
          disabled={!name.trim() || !requiredOk}
          style={{ fontSize: 11 }}
          onClick={() => onSave({ name: name.trim(), configuration })}
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

function NewProviderForm({
  onSave,
  onCancel,
}: {
  onSave: (provider: { name: string; provider: string; configuration: Record<string, unknown>; enabled: boolean }) => void;
  onCancel: () => void;
}) {
  const [providerType, setProviderType] = useState<keyof typeof PROVIDER_FIELD_META>("ntfy");
  const [name, setName] = useState("");
  const [configuration, setConfiguration] = useState<Record<string, unknown>>({});
  const meta = PROVIDER_FIELD_META[providerType];
  const requiredOk = meta.fields.every((f) => f.optional || String(configuration[f.key] ?? "").trim());

  const changeType = (t: keyof typeof PROVIDER_FIELD_META) => {
    setProviderType(t);
    setConfiguration({});
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.4rem",
        padding: "0.5rem 0.75rem 0.7rem",
        fontSize: 12,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <span className="microlabel" style={{ minWidth: 70 }}>Proveedor</span>
        <select className="input" value={providerType} onChange={(e) => changeType(e.target.value as keyof typeof PROVIDER_FIELD_META)}>
          {Object.entries(PROVIDER_FIELD_META).map(([type, m]) => (
            <option key={type} value={type}>{m.label}</option>
          ))}
        </select>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <span className="microlabel" style={{ minWidth: 70 }}>Nombre</span>
        <input className="input" style={{ flex: 1 }} placeholder="p. ej. Bot de guardia" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <ProviderFieldsEditor providerType={providerType} configuration={configuration} onChange={setConfiguration} />
      <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.2rem" }}>
        <button
          className="btn"
          disabled={!name.trim() || !requiredOk}
          style={{ fontSize: 11 }}
          onClick={() => {
            onSave({ name: name.trim(), provider: providerType, configuration, enabled: true });
          }}
        >
          Crear integración
        </button>
        <button className="btn ghost" style={{ fontSize: 11 }} onClick={onCancel}>
          Cancelar
        </button>
      </div>
    </div>
  );
}

function ChannelForm({
  channel,
  providers,
  onSave,
  onCancel,
}: {
  channel?: ChannelOut;
  providers: ProviderOut[];
  onSave: (changes: { name: string; description: string | null; provider_ids: number[] }) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(channel?.name ?? "");
  const [description, setDescription] = useState(channel?.description ?? "");
  const [providerIds, setProviderIds] = useState<number[]>(channel?.provider_ids ?? []);

  const toggle = (id: number) =>
    setProviderIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.4rem",
        padding: "0.5rem 0.75rem 0.7rem",
        fontSize: 12,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <span className="microlabel" style={{ minWidth: 70 }}>Nombre</span>
        <input className="input" style={{ flex: 1 }} placeholder="p. ej. Operadores" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <span className="microlabel" style={{ minWidth: 70 }}>Descripción</span>
        <input className="input" style={{ flex: 1 }} value={description} onChange={(e) => setDescription(e.target.value)} />
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
        <span className="microlabel">Integraciones</span>
        {providers.length === 0 && (
          <span style={{ color: "var(--text-faint)", fontSize: 11 }}>Sin integraciones creadas todavía.</span>
        )}
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
          {providers.map((p) => (
            <label key={p.id} style={{ display: "flex", alignItems: "center", gap: "0.3rem", fontSize: 11.5 }}>
              <input type="checkbox" checked={providerIds.includes(p.id)} onChange={() => toggle(p.id)} />
              {p.name} <span className="chip">{p.provider}</span>
            </label>
          ))}
        </div>
      </div>
      <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.2rem" }}>
        <button
          className="btn"
          disabled={!name.trim()}
          style={{ fontSize: 11 }}
          onClick={() => onSave({ name: name.trim(), description: description.trim() || null, provider_ids: providerIds })}
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
    queryClient.invalidateQueries({ queryKey: ["providers"] });
    queryClient.invalidateQueries({ queryKey: ["channels"] });
  };

  const alerts = useQuery({ queryKey: ["alerts"], queryFn: () => fetchAlerts(undefined, 100), refetchInterval: 30_000 });
  const rules = useQuery({ queryKey: ["alert-rules"], queryFn: fetchAlertRules });
  // Nombre del grupo para el chip de ámbito de las reglas por grupo (§1.3)
  const groups = useQuery({ queryKey: ["groups"], queryFn: fetchGroups });
  const groupName = (id: number | null) =>
    id == null ? null : ((groups.data ?? []).find((g) => g.id === id)?.name ?? `#${id}`);
  const providers = useQuery({ queryKey: ["providers"], queryFn: fetchProviders });
  const channels = useQuery({ queryKey: ["channels"], queryFn: fetchChannels });
  const channelName = (id: number) => (channels.data ?? []).find((c) => c.id === id)?.name ?? `#${id}`;
  // Mismo queryKey que App.tsx/GroupContext: caché compartida, sin fetch nuevo.
  const nodes = useQuery({ queryKey: ["nodes"], queryFn: () => fetchNodes() });
  const groupNodeIds = useGroupNodeIds(nodes.data ?? []);
  const nodeLabel = (id: string | null) => {
    if (id == null) return null;
    const node = (nodes.data ?? []).find((n) => n.node.node_id === id);
    return node ? displayName(node.node) : id;
  };

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
  // Editor abierto ↔ URL (`alerts.edit`, ADR 0026 / docs/design/urls-compartibles.md
  // §3.6): un único parámetro (`rule:{id}` | `provider:{id}` | `channel:{id}` |
  // `new-rule` | `new-provider` | `new-channel`) — como mucho un editor
  // abierto a la vez, igual que hoy. Los campos del formulario en curso NO
  // viajan en la URL (ver ADR): abrir el enlace reabre con los valores
  // actuales de esa regla/proveedor/canal, no con un borrador ajeno.
  const [alertsEdit, setAlertsEdit] = useUrlString("alerts.edit", null, { replace: true });
  const creatingRule = alertsEdit === "new-rule";
  const editingRuleId = alertsEdit?.startsWith("rule:") ? Number(alertsEdit.slice(5)) : null;
  const creatingProvider = alertsEdit === "new-provider";
  const editingProviderId = alertsEdit?.startsWith("provider:") ? Number(alertsEdit.slice(9)) : null;
  const creatingChannel = alertsEdit === "new-channel";
  const editingChannelId = alertsEdit?.startsWith("channel:") ? Number(alertsEdit.slice(8)) : null;
  const setCreatingRule = (v: boolean) => setAlertsEdit(v ? "new-rule" : null);
  const setEditingRuleId = (id: number | null) => setAlertsEdit(id != null ? `rule:${id}` : null);
  const setCreatingProvider = (v: boolean) => setAlertsEdit(v ? "new-provider" : null);
  const setEditingProviderId = (id: number | null) => setAlertsEdit(id != null ? `provider:${id}` : null);
  const setCreatingChannel = (v: boolean) => setAlertsEdit(v ? "new-channel" : null);
  const setEditingChannelId = (id: number | null) => setAlertsEdit(id != null ? `channel:${id}` : null);

  const addProvider = useMutation({ mutationFn: createProvider, onSettled: invalidate });
  const editProvider = useMutation({
    mutationFn: ({ id, changes }: { id: number; changes: { name: string; configuration: Record<string, unknown> } }) =>
      patchProvider(id, changes),
    onSettled: invalidate,
  });
  const toggleProvider = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => patchProvider(id, { enabled }),
    onSettled: invalidate,
  });
  const removeProvider = useMutation({ mutationFn: deleteProvider, onSettled: invalidate });
  const dupProvider = useMutation({ mutationFn: duplicateProvider, onSettled: invalidate });
  const testProviderMut = useMutation({ mutationFn: testProvider });

  const addChannelGroup = useMutation({ mutationFn: createChannel, onSettled: invalidate });
  const editChannelGroup = useMutation({
    mutationFn: ({ id, changes }: { id: number; changes: { name: string; description: string | null; provider_ids: number[] } }) =>
      patchChannel(id, changes),
    onSettled: invalidate,
  });
  const removeChannelGroup = useMutation({ mutationFn: deleteChannel, onSettled: invalidate });

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
          <div className="v" style={{ color: "var(--text-dim)" }}>{(providers.data ?? []).length}</div>
          <div className="k">Integraciones</div>
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
                onClick={() => setCreatingRule(true)}
              >
                + Nueva
              </button>
            </div>
            <div className="panel-body flush">
              {(rules.data ?? []).map((r) => (
                <div
                  key={r.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.6rem",
                    padding: "0.4rem 0.75rem",
                    borderBottom: "1px solid var(--border-subtle)",
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
                  <span style={{ color: r.enabled ? "var(--text)" : "var(--text-faint)", flex: 1 }}>
                    {r.name}
                    {r.group_id != null && (
                      <span className="chip" style={{ marginLeft: 6 }} title="Regla escopada a un grupo">
                        ◉ {groupName(r.group_id)}
                      </span>
                    )}
                    {r.node_id != null && (
                      <span className="chip" style={{ marginLeft: 6 }} title="Regla escopada a un nodo">
                        ◎ {nodeLabel(r.node_id)}
                      </span>
                    )}
                    {r.channel_ids.length > 0 && (
                      <span className="chip" style={{ marginLeft: 6 }} title={r.channel_ids.map(channelName).join(", ")}>
                        ✉ {r.channel_ids.length}
                      </span>
                    )}
                  </span>
                  <button
                    className="btn ghost"
                    style={{ padding: "0.1rem 0.5rem", fontSize: 11 }}
                    onClick={() => setEditingRuleId(r.id)}
                  >
                    Ajustar
                  </button>
                  <button
                    className="btn ghost"
                    style={{ padding: "0.1rem 0.5rem", fontSize: 11 }}
                    title="Borrar regla"
                    onClick={() => {
                      if (window.confirm(`¿Borrar la regla «${r.name}»?`)) removeRule.mutate(r.id);
                    }}
                  >
                    ✕
                  </button>
                </div>
              ))}
              {(rules.data ?? []).length === 0 && <div className="empty">Sin reglas creadas.</div>}
            </div>
          </div>

          <div className="panel" style={{ flex: 1 }}>
            <div className="panel-head">
              <span className="panel-title">Integraciones</span>
              <span className="panel-count">{(providers.data ?? []).length}</span>
              <button
                className="btn ghost"
                style={{ marginLeft: "auto", padding: "0.1rem 0.5rem", fontSize: 11 }}
                onClick={() => setCreatingProvider(true)}
              >
                + Nueva
              </button>
            </div>
            <div className="panel-body flush">
              {(providers.data ?? []).length === 0 && (
                <div className="empty">Sin integraciones. Las alertas solo se verán en el NOC.</div>
              )}
              {(providers.data ?? []).map((p) => (
                <div
                  key={p.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    fontSize: 12,
                    padding: "0.4rem 0.75rem",
                    borderBottom: "1px solid var(--border-subtle)",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={p.enabled}
                    title={p.enabled ? "Integración activa" : "Integración desactivada"}
                    onChange={(e) => toggleProvider.mutate({ id: p.id, enabled: e.target.checked })}
                  />
                  <span className="mono" style={{ color: p.enabled ? "var(--text)" : "var(--text-faint)" }}>{p.name}</span>
                  <span className="chip">{PROVIDER_FIELD_META[p.provider]?.label ?? p.provider}</span>
                  <span style={{ marginLeft: "auto", display: "flex", gap: "0.3rem" }}>
                    <button className="btn ghost" style={{ fontSize: 11 }} onClick={() => testProviderMut.mutate(p.id)}>Probar</button>
                    <button className="btn ghost" style={{ fontSize: 11 }} onClick={() => dupProvider.mutate(p.id)}>Duplicar</button>
                    <button className="btn ghost" style={{ fontSize: 11 }} onClick={() => setEditingProviderId(p.id)}>
                      Editar
                    </button>
                    <button
                      className="btn ghost"
                      style={{ fontSize: 11 }}
                      onClick={() => {
                        if (window.confirm(`¿Borrar la integración «${p.name}»?`)) removeProvider.mutate(p.id);
                      }}
                    >
                      ✕
                    </button>
                  </span>
                </div>
              ))}
              {testProviderMut.isSuccess && <p style={{ color: "var(--ok)", fontSize: 12, padding: "0 0.75rem" }}>Mensaje de prueba enviado.</p>}
              {testProviderMut.isError && <p style={{ color: "var(--crit)", fontSize: 12, padding: "0 0.75rem" }}>{String(testProviderMut.error)}</p>}
            </div>
          </div>

          <div className="panel" style={{ flex: 1 }}>
            <div className="panel-head">
              <span className="panel-title">Canales</span>
              <span className="panel-count">{(channels.data ?? []).length}</span>
              <button
                className="btn ghost"
                style={{ marginLeft: "auto", padding: "0.1rem 0.5rem", fontSize: 11 }}
                onClick={() => setCreatingChannel(true)}
              >
                + Nuevo
              </button>
            </div>
            <div className="panel-body flush">
              {(channels.data ?? []).length === 0 && (
                <div className="empty">Sin canales — las reglas sin canal asignado difunden a todas las integraciones activas.</div>
              )}
              {(channels.data ?? []).map((c) => (
                <div
                  key={c.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    fontSize: 12,
                    padding: "0.4rem 0.75rem",
                    borderBottom: "1px solid var(--border-subtle)",
                  }}
                >
                  <span className="mono" style={{ color: "var(--text)" }}>{c.name}</span>
                  <span className="chip">{c.provider_ids.length} integr.</span>
                  <span style={{ marginLeft: "auto", display: "flex", gap: "0.3rem" }}>
                    <button className="btn ghost" style={{ fontSize: 11 }} onClick={() => setEditingChannelId(c.id)}>
                      Editar
                    </button>
                    <button
                      className="btn ghost"
                      style={{ fontSize: 11 }}
                      onClick={() => {
                        if (window.confirm(`¿Borrar el canal «${c.name}»?`)) removeChannelGroup.mutate(c.id);
                      }}
                    >
                      ✕
                    </button>
                  </span>
                </div>
              ))}
              {addChannelGroup.isError && <p style={{ color: "var(--crit)", fontSize: 12, padding: "0 0.75rem" }}>{String(addChannelGroup.error)}</p>}
            </div>
          </div>
        </div>
      </div>

      {creatingRule && (
        <Modal title="Nueva regla" onClose={() => setCreatingRule(false)}>
          <NewRuleForm
            channels={channels.data ?? []}
            onCancel={() => setCreatingRule(false)}
            onSave={(rule) => {
              newRule.mutate(rule);
              setCreatingRule(false);
            }}
          />
        </Modal>
      )}
      {editingRuleId != null && (() => {
        const rule = (rules.data ?? []).find((r) => r.id === editingRuleId);
        return rule ? (
          <Modal title={`Ajustar «${rule.name}»`} onClose={() => setEditingRuleId(null)}>
            <RuleEditor
              rule={rule}
              channels={channels.data ?? []}
              onCancel={() => setEditingRuleId(null)}
              onSave={(changes) => {
                editRule.mutate({ id: rule.id, changes });
                setEditingRuleId(null);
              }}
            />
          </Modal>
        ) : null;
      })()}

      {creatingProvider && (
        <Modal title="Nueva integración" onClose={() => setCreatingProvider(false)}>
          <NewProviderForm
            onCancel={() => setCreatingProvider(false)}
            onSave={(provider) => {
              addProvider.mutate(provider);
              setCreatingProvider(false);
            }}
          />
        </Modal>
      )}
      {editingProviderId != null && (() => {
        const provider = (providers.data ?? []).find((p) => p.id === editingProviderId);
        return provider ? (
          <Modal title={`Editar «${provider.name}»`} onClose={() => setEditingProviderId(null)}>
            <ProviderEditor
              provider={provider}
              onCancel={() => setEditingProviderId(null)}
              onSave={(changes) => {
                editProvider.mutate({ id: provider.id, changes });
                setEditingProviderId(null);
              }}
            />
          </Modal>
        ) : null;
      })()}

      {creatingChannel && (
        <Modal title="Nuevo canal" onClose={() => setCreatingChannel(false)}>
          <ChannelForm
            providers={providers.data ?? []}
            onCancel={() => setCreatingChannel(false)}
            onSave={(channel) => {
              addChannelGroup.mutate(channel);
              setCreatingChannel(false);
            }}
          />
        </Modal>
      )}
      {editingChannelId != null && (() => {
        const channel = (channels.data ?? []).find((c) => c.id === editingChannelId);
        return channel ? (
          <Modal title={`Editar «${channel.name}»`} onClose={() => setEditingChannelId(null)}>
            <ChannelForm
              channel={channel}
              providers={providers.data ?? []}
              onCancel={() => setEditingChannelId(null)}
              onSave={(changes) => {
                editChannelGroup.mutate({ id: channel.id, changes });
                setEditingChannelId(null);
              }}
            />
          </Modal>
        ) : null;
      })()}
    </div>
  );
}

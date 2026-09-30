import { useMemo, useState, type CSSProperties } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchGateways,
  fetchNexusCatalog,
  fetchNexusSettings,
  patchNexusSettings,
  type NexusPinnedNode,
  type NexusSettingsOut,
  type NexusTemplate,
} from "../../api/client";
import { toast } from "../shell/Toast";
import { t } from "../../tokens";

const btn: CSSProperties = {
  background: "transparent",
  border: `1px solid ${t.border}`,
  color: t.text,
  borderRadius: 4,
  cursor: "pointer",
  fontSize: 11,
  padding: "0.1rem 0.5rem",
};

const input: CSSProperties = {
  background: t.bg,
  border: `1px solid ${t.border}`,
  color: t.text,
  borderRadius: 4,
  padding: "0.2rem 0.4rem",
  fontSize: 12,
};

const label: CSSProperties = {
  display: "block",
  color: t.textDim,
  fontSize: 11,
  fontWeight: 600,
  marginBottom: 3,
};

const field: CSSProperties = { minWidth: 180 };

/**
 * Ajustes del módulo JenTastic-Nexus (ADR 0027 §13) — pedido explícito del
 * usuario: "en los ajustes, al pinchar en activar Nexus, quiero ajustes
 * debajo". Cada control hace PATCH /nexus/settings al perder el foco/
 * cambiar — sin botón "Guardar" global, mismo criterio inmediato que el
 * resto de Ajustes (SettingsView.tsx). Solo administradores pueden
 * escribir (backend, RequireAdminDep); la vista entera ya está detrás de
 * esa puerta a nivel de navegación (App.tsx).
 */
export function NexusSettingsPanel() {
  const queryClient = useQueryClient();
  const settingsQuery = useQuery({ queryKey: ["nexus-settings"], queryFn: fetchNexusSettings });
  const gatewaysQuery = useQuery({ queryKey: ["gateways"], queryFn: () => fetchGateways() });
  const settings = settingsQuery.data;

  const patch = useMutation({
    mutationFn: (changes: Partial<NexusSettingsOut>) => patchNexusSettings(changes),
    onSuccess: (data) => {
      queryClient.setQueryData(["nexus-settings"], data);
      toast("Ajuste guardado");
    },
    onError: (err) =>
      toast(err instanceof Error ? err.message.replace(/^HTTP \d+: /, "") : "No se pudo guardar", { kind: "error" }),
  });

  if (!settings) {
    return <div style={{ color: t.textFaint, fontSize: 12, marginTop: 8 }}>Cargando ajustes…</div>;
  }

  return (
    <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 14 }}>
      <h3 style={{ fontSize: 13, textTransform: "uppercase", letterSpacing: "0.06em", color: t.textDim, margin: 0 }}>
        Ajustes de JenTastic-Nexus
      </h3>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 14 }}>
        <div style={field}>
          <label style={label} title="Solo cambia la opción preseleccionada al abrir la pestaña Nexus de un nodo — sigues pudiendo elegir la otra a mano.">
            Direccionar un nodo por defecto
          </label>
          <select
            className="input"
            style={input}
            value={settings.addressing_mode}
            onChange={(e) => patch.mutate({ addressing_mode: e.target.value as NexusSettingsOut["addressing_mode"] })}
          >
            <option value="shortname">Nombre corto (-node) — recomendado</option>
            <option value="device_id">Node ID (-device)</option>
          </select>
          {settings.addressing_mode === "device_id" && (
            <div style={{ color: t.warn, fontSize: 10.5, marginTop: 3, maxWidth: 220 }}>
              ⚠ el node_id puede cambiar al reflashear (firmware 2.8+) — si un
              nodo deja de responder, prueba con su nombre corto.
            </div>
          )}
        </div>

        <div style={field}>
          <label style={label} title="El texto que antecede a cada comando, p. ej. «/nexus STATS». Cámbialo solo si tu firmware usa un prefijo distinto.">
            Prefijo de comando
          </label>
          <input
            className="input mono"
            style={input}
            defaultValue={settings.command_prefix}
            onBlur={(e) => {
              const v = e.target.value.trim();
              if (v && v !== settings.command_prefix) patch.mutate({ command_prefix: v });
            }}
          />
        </div>

        <div style={field}>
          <label
            style={label}
            title="Nombre exacto del canal LoRa por el que salen los comandos /nexus. Vacío = autodetección ('Nexus'/'JenT', insensible a mayúsculas). Si se fija uno y el nodo local no lo tiene configurado, el envío se rechaza en vez de usar el canal principal."
          >
            Canal de salida de comandos
          </label>
          <input
            className="input mono"
            style={input}
            placeholder="automático (Nexus / JenT)"
            defaultValue={settings.channel_name ?? ""}
            onBlur={(e) => {
              const v = e.target.value.trim();
              if (v !== (settings.channel_name ?? "")) patch.mutate({ channel_name: v || null });
            }}
          />
        </div>

        <div style={field}>
          <label style={label}>Ventana de respuesta (s)</label>
          <input
            type="number"
            min={1}
            className="input"
            style={input}
            defaultValue={settings.response_window_seconds}
            onBlur={(e) => {
              const v = Number(e.target.value);
              if (v > 0 && v !== settings.response_window_seconds) patch.mutate({ response_window_seconds: v });
            }}
          />
        </div>

        <div style={field}>
          <label style={label}>Cadencia mínima entre escaneos (s)</label>
          <input
            type="number"
            min={1}
            className="input"
            style={input}
            defaultValue={settings.scan_cooldown_seconds}
            onBlur={(e) => {
              const v = Number(e.target.value);
              if (v > 0 && v !== settings.scan_cooldown_seconds) patch.mutate({ scan_cooldown_seconds: v });
            }}
          />
        </div>

        <div style={field}>
          <label style={label}>Destino por defecto (Ajustes → Operaciones)</label>
          <select
            className="input"
            style={input}
            value={settings.default_target_kind}
            onChange={(e) => patch.mutate({ default_target_kind: e.target.value as NexusSettingsOut["default_target_kind"] })}
          >
            <option value="broadcast">Difusión</option>
            <option value="local">Local</option>
            <option value="node">Nodo (nombre corto)</option>
            <option value="device">Nodo (node_id)</option>
            <option value="mac">MAC</option>
            <option value="group">Grupo Nexus</option>
          </select>
        </div>

        <div style={field}>
          <label style={label}>Pasarela por defecto</label>
          <select
            className="input"
            style={input}
            value={settings.default_gateway_id ?? ""}
            onChange={(e) => patch.mutate({ default_gateway_id: e.target.value || null })}
          >
            <option value="">— sin preferencia —</option>
            {(gatewaysQuery.data ?? []).map((g) => (
              <option key={g.gateway_id} value={g.gateway_id}>{g.name || g.gateway_id}</option>
            ))}
          </select>
        </div>

        <div style={{ ...field, display: "flex", flexDirection: "column", gap: 6, justifyContent: "flex-end" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5, color: t.textDim, cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={settings.catalog_collapsed_default}
              onChange={(e) => patch.mutate({ catalog_collapsed_default: e.target.checked })}
            />
            Explorador de catálogo replegado por defecto
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5, color: t.textDim, cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={settings.notify_on_broadcast_complete}
              onChange={(e) => patch.mutate({ notify_on_broadcast_complete: e.target.checked })}
            />
            Avisar cuando termine una difusión
          </label>
          <label
            style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5, color: t.textDim, cursor: "pointer" }}
            title="Sugiere nodos JT sin mandar nada: observa el tráfico que ya llega por el canal Nexus. Sigue siendo solo sugerencia — el marcado siempre lo confirma un operador."
          >
            <input
              type="checkbox"
              checked={settings.passive_detection_enabled}
              onChange={(e) => patch.mutate({ passive_detection_enabled: e.target.checked })}
            />
            Detección pasiva de nodos JT (sin enviar nada)
          </label>
        </div>
      </div>

      <HiddenCommandsEditor
        hidden={settings.hidden_commands}
        onChange={(next) => patch.mutate({ hidden_commands: next })}
      />
      <PinnedNodesEditor
        nodes={settings.pinned_nodes}
        onChange={(next) => patch.mutate({ pinned_nodes: next })}
      />
      <TemplatesEditor
        templates={settings.templates}
        onChange={(next) => patch.mutate({ templates: next })}
      />
    </div>
  );
}

function HiddenCommandsEditor({ hidden, onChange }: { hidden: string[]; onChange: (next: string[]) => void }) {
  const [open, setOpen] = useState(false);
  const catalog = useQuery({ queryKey: ["nexus-catalog"], queryFn: fetchNexusCatalog, enabled: open });
  const [filter, setFilter] = useState("");
  const hiddenSet = useMemo(() => new Set(hidden), [hidden]);

  const filtered = (catalog.data ?? []).filter((c) => c.name.includes(filter.trim().toUpperCase()));

  const toggle = (name: string) => {
    const next = new Set(hiddenSet);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    onChange([...next]);
  };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={label}>Ocultar comandos del explorador de catálogo ({hidden.length} ocultos)</span>
        <button style={btn} onClick={() => setOpen((v) => !v)}>{open ? "Cerrar ▴" : "Editar lista ▾"}</button>
        {hidden.length > 0 && (
          <button style={btn} onClick={() => onChange([])}>Mostrar todos</button>
        )}
      </div>
      {open && (
        <div style={{ marginTop: 6, border: `1px solid ${t.borderSubtle}`, borderRadius: 6, background: t.surface2, maxHeight: 260, overflowY: "auto", padding: "0.4rem 0.5rem" }}>
          <input
            placeholder="Filtrar…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{ ...input, width: "100%", boxSizing: "border-box", marginBottom: 6 }}
          />
          {catalog.isLoading && <div style={{ color: t.textFaint, fontSize: 11.5 }}>Cargando…</div>}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "2px 8px" }}>
            {filtered.map((c) => (
              <label
                key={c.name}
                title={c.description || undefined}
                style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, fontFamily: t.fontMono, cursor: "pointer" }}
              >
                <input type="checkbox" checked={hiddenSet.has(c.name)} onChange={() => toggle(c.name)} />
                {c.name}
                {c.description && <span style={{ color: t.textFaint, fontSize: 10 }}>ⓘ</span>}
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function PinnedNodesEditor({ nodes, onChange }: { nodes: NexusPinnedNode[]; onChange: (next: NexusPinnedNode[]) => void }) {
  const [shortName, setShortName] = useState("");
  const [nodeLabel, setNodeLabel] = useState("");
  return (
    <div>
      <span style={label}>Nodos fijados (atajos)</span>
      <div style={{ display: "flex", flexDirection: "column", gap: 3, marginTop: 3 }}>
        {nodes.length === 0 && <div style={{ color: t.textFaint, fontSize: 11.5 }}>Ninguno todavía.</div>}
        {nodes.map((n) => (
          <div key={n.short_name} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5 }}>
            <span className="mono" style={{ flex: 1 }}>{n.short_name} <span style={{ color: t.textFaint }}>{n.label !== n.short_name ? `— ${n.label}` : ""}</span></span>
            <button style={btn} onClick={() => onChange(nodes.filter((x) => x.short_name !== n.short_name))}>Quitar</button>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
        <input style={{ ...input, width: 100, fontFamily: t.fontMono }} placeholder="nombre corto" value={shortName} onChange={(e) => setShortName(e.target.value)} />
        <input style={{ ...input, width: 130 }} placeholder="etiqueta (opcional)" value={nodeLabel} onChange={(e) => setNodeLabel(e.target.value)} />
        <button
          style={btn}
          disabled={!shortName.trim()}
          onClick={() => {
            onChange([...nodes.filter((x) => x.short_name !== shortName.trim()), { short_name: shortName.trim(), label: nodeLabel.trim() || shortName.trim() }]);
            setShortName("");
            setNodeLabel("");
          }}
        >
          Añadir
        </button>
      </div>
    </div>
  );
}

function TemplatesEditor({ templates, onChange }: { templates: NexusTemplate[]; onChange: (next: NexusTemplate[]) => void }) {
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [tplLabel, setTplLabel] = useState("");
  return (
    <div>
      <span style={label}>Plantillas de comando</span>
      <div style={{ display: "flex", flexDirection: "column", gap: 3, marginTop: 3 }}>
        {templates.length === 0 && <div style={{ color: t.textFaint, fontSize: 11.5 }}>Ninguna todavía.</div>}
        {templates.map((tpl) => (
          <div key={tpl.label + tpl.command} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5 }}>
            <span style={{ flex: 1 }}>
              <strong>{tpl.label}</strong>{" "}
              <span className="mono" style={{ color: t.textFaint }}>{tpl.command} {tpl.args}</span>
            </span>
            <button style={btn} onClick={() => onChange(templates.filter((x) => x !== tpl))}>Quitar</button>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
        <input style={{ ...input, width: 110 }} placeholder="etiqueta" value={tplLabel} onChange={(e) => setTplLabel(e.target.value)} />
        <input style={{ ...input, width: 110, fontFamily: t.fontMono }} placeholder="COMANDO" value={command} onChange={(e) => setCommand(e.target.value)} />
        <input style={{ ...input, width: 140, fontFamily: t.fontMono }} placeholder="argumentos" value={args} onChange={(e) => setArgs(e.target.value)} />
        <button
          style={btn}
          disabled={!command.trim()}
          onClick={() => {
            onChange([...templates, { label: tplLabel.trim() || command.trim(), command: command.trim().toUpperCase(), args: args.trim() }]);
            setCommand(""); setArgs(""); setTplLabel("");
          }}
        >
          Añadir
        </button>
      </div>
    </div>
  );
}


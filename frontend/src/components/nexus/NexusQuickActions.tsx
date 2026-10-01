import { useMemo, useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchNexusCatalog, fetchNexusSettings } from "../../api/client";
import { t } from "../../tokens";
import { NexusCatalogWizard } from "./NexusCatalogBrowser";
import type { NexusNodeOption } from "./NexusArgsField";

interface QuickAction {
  icon: string;
  label: string;
  hint: string;
  command: string;
  /** Con `variant`, el botón abre el asistente posicionado ahí (pide un nodo,
   * un valor...); sin él se previsualiza directo (consultas sin argumentos). */
  variant?: string;
  args?: string[];
  danger?: boolean;
}

// Acciones que más se usan. Todas salen del catálogo (el backend sigue
// validando); las de consulta no piden nada, las "con nodo" abren el
// asistente en la variante correcta. Ninguna envía sola.
const QUERIES: QuickAction[] = [
  { icon: "ℹ️", label: "Info", hint: "Identidad, versión y rol", command: "INFO" },
  { icon: "⏱", label: "Uptime", hint: "Tiempo encendido", command: "UPTIME" },
  { icon: "⚙️", label: "Resumen", hint: "Rol, saltos, firewall…", command: "SETTINGS" },
  { icon: "🔐", label: "Seguridad", hint: "Firma, DM, anti-replay", command: "SECURITY" },
  { icon: "⭐", label: "Favoritos", hint: "Lista de favoritos", command: "FAVS" },
  { icon: "🚫", label: "Ignorados", hint: "Lista de ignorados", command: "IGNORED" },
  { icon: "↔️", label: "Zero-Hop", hint: "Relays ZH activos", command: "ZH", args: ["LIST"] },
  { icon: "🛡", label: "Ignorados NIGN", hint: "Lista persistente", command: "NIGN", args: ["LIST"] },
];

const WITH_NODE: QuickAction[] = [
  { icon: "⭐", label: "Marcar favorito", hint: "FAV", command: "FAV", variant: "Marcar como favorito" },
  { icon: "☆", label: "Quitar favorito", hint: "UNFAV", command: "UNFAV", variant: "Quitar de favoritos" },
  { icon: "🚫", label: "Ignorar nodo", hint: "IGNORE", command: "IGNORE", variant: "Ignorar nodo" },
  { icon: "✅", label: "Dejar de ignorar", hint: "UNIGNORE", command: "UNIGNORE", variant: "Dejar de ignorar" },
  { icon: "↔️", label: "Añadir a Zero-Hop", hint: "ZH ADD", command: "ZH", variant: "Añadir relay" },
  { icon: "➖", label: "Quitar de Zero-Hop", hint: "ZH DEL", command: "ZH", variant: "Quitar relay" },
  { icon: "👁", label: "Vigilar nodo", hint: "WATCH ADD", command: "WATCH", variant: "Añadir objetivo" },
  { icon: "📊", label: "Estadísticas vigilado", hint: "WATCH STATS", command: "WATCH", variant: "Estadísticas de un objetivo" },
];

const grid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
  gap: 8,
};

const bigBtn: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  minHeight: 56,
  padding: "0.5rem 0.75rem",
  textAlign: "left",
  background: t.surface2,
  border: `1px solid ${t.border}`,
  borderRadius: 8,
  color: t.text,
  cursor: "pointer",
  font: "inherit",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ color: t.textFaint, fontSize: 10.5, letterSpacing: 0.6, margin: "0 0 5px" }}>{title}</div>
      <div style={grid}>{children}</div>
    </div>
  );
}

/**
 * Botones grandes para lo que más se usa en la consola. Nunca envían: las
 * consultas rellenan el formulario y previsualizan (`onRun`), las acciones con
 * nodo abren el asistente en la variante correcta y entregan el resultado por
 * `onSelect`; después sigue haciendo falta confirmar y añadir a la cola.
 * Las plantillas de Ajustes aparecen aquí también, como botones grandes.
 */
export function NexusQuickActions({
  onRun, onSelect, nodeOptions, disabledReason,
}: {
  onRun: (command: string, args: string[]) => void;
  onSelect: (command: string, args: string[]) => void;
  nodeOptions: NexusNodeOption[];
  /** Si hay motivo (falta pasarela/destino) se muestra en vez de ejecutar. */
  disabledReason: string | null;
}) {
  const catalog = useQuery({ queryKey: ["nexus-catalog"], queryFn: fetchNexusCatalog });
  const settings = useQuery({ queryKey: ["nexus-settings"], queryFn: fetchNexusSettings });
  const hidden = useMemo(() => new Set(settings.data?.hidden_commands ?? []), [settings.data]);
  const [guided, setGuided] = useState<QuickAction | null>(null);

  const templates = settings.data?.templates ?? [];
  const known = new Set((catalog.data ?? []).map((e) => e.name));
  const available = (a: QuickAction) => !catalog.data || known.has(a.command);

  const press = (a: QuickAction) => {
    if (a.variant) setGuided(a);
    else onRun(a.command, a.args ?? []);
  };

  const render = (a: QuickAction) => (
    <button key={`${a.command}-${a.label}`} style={bigBtn} onClick={() => press(a)}
      title={a.variant ? "Abre el asistente para elegir el nodo" : "Previsualiza este comando"}>
      <span style={{ fontSize: 22, lineHeight: 1 }}>{a.icon}</span>
      <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: a.danger ? t.crit : t.text }}>{a.label}</span>
        <span className="mono" style={{ fontSize: 10, color: t.textFaint }}>{a.hint}</span>
      </span>
    </button>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {disabledReason && (
        <div style={{ color: t.warn, fontSize: 11 }}>Antes de pulsar: {disabledReason}</div>
      )}
      <Section title="CONSULTAS RÁPIDAS">{QUERIES.filter(available).map(render)}</Section>
      <Section title="ACCIONES SOBRE UN NODO">{WITH_NODE.filter(available).map(render)}</Section>
      {templates.length > 0 && (
        <Section title="TUS PLANTILLAS">
          {templates.map((tpl) =>
            render({
              icon: "★", label: tpl.label, hint: `${tpl.command} ${tpl.args}`.trim(),
              command: tpl.command, args: tpl.args.trim() ? tpl.args.trim().split(/\s+/) : [],
            }),
          )}
        </Section>
      )}
      {guided && catalog.data && (
        <NexusCatalogWizard
          catalog={catalog.data}
          hidden={hidden}
          nodeOptions={nodeOptions}
          initialName={guided.command}
          initialVariantLabel={guided.variant}
          onSelect={onSelect}
          onClose={() => setGuided(null)}
        />
      )}
    </div>
  );
}

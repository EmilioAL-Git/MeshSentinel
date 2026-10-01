import { useMemo, useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchNexusCatalog,
  fetchNexusSettings,
  type NexusCatalogEntryOut,
  type NexusSyntaxArg,
  type NexusSyntaxVariant,
} from "../../api/client";
import { Modal } from "../shell/Modal";
import { t } from "../../tokens";
import type { NexusNodeOption } from "./NexusArgsField";

const CATEGORY_LABEL: Record<string, string> = {
  system: "Sistema",
  stats: "Estadísticas",
  scan: "Escaneo",
  nodedb: "Base de nodos",
  firewall: "Cortafuegos",
  stealth: "Sigilo",
  injection: "Inyección (pruebas)",
  config: "Configuración",
  sensors: "Sensores",
  storage: "Almacenamiento",
  alerts: "Alertas",
  pping: "Ping periódico",
  security: "Seguridad",
  critical: "Crítico",
};

// Orden fijo (§3 del manual): más útil que alfabético para explorar.
const CATEGORY_ORDER = [
  "system", "stats", "scan", "nodedb", "firewall", "stealth", "injection",
  "config", "sensors", "storage", "alerts", "pping", "security", "critical",
];

const NODE_RE = /^(![0-9a-fA-F]{8}|\S{1,12})$/;
const HEX_RE = /^(0x|\*)?[0-9a-fA-F]{1,16}$/;

/** Mensaje de error de un valor, o `null` si vale (campo opcional vacío = vale). */
export function validateArg(arg: NexusSyntaxArg, raw: string): string | null {
  const value = raw.trim();
  if (!value) return arg.optional ? null : "Obligatorio";
  if (/[;\n]/.test(value)) return "No puede contener «;» ni saltos de línea";
  switch (arg.kind) {
    case "number": {
      if (!/^-?\d+$/.test(value)) return "Debe ser un número entero";
      const n = Number(value);
      if (arg.min !== null && n < arg.min) return `Mínimo ${arg.min}`;
      if (arg.max !== null && n > arg.max) return `Máximo ${arg.max}`;
      return null;
    }
    case "hex":
      return HEX_RE.test(value) ? null : "Valor hexadecimal (p. ej. 0xC3)";
    case "node":
      return NODE_RE.test(value) ? null : "!xxxxxxxx (8 hex) o nombre corto";
    case "choice":
      return arg.choices.includes(value) ? null : "Elige una opción";
    case "onoff":
      return value === arg.on_value || value === arg.off_value ? null : "ON u OFF";
    default:
      return null;
  }
}

/** Tokens finales a enviar: fijos de la variante + valores rellenados (los
 * opcionales vacíos se omiten). Texto libre viaja como un único argumento. */
export function assembleArgs(variant: NexusSyntaxVariant, values: Record<string, string>): string[] {
  const out = [...variant.tokens];
  for (const arg of variant.args) {
    const v = (values[arg.name] ?? "").trim();
    if (v) out.push(v);
  }
  return out;
}

const chip: CSSProperties = {
  background: "transparent",
  border: `1px solid ${t.border}`,
  color: t.text,
  borderRadius: 999,
  cursor: "pointer",
  fontSize: 11.5,
  padding: "0.15rem 0.6rem",
};

const listBtn: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  gap: 6,
  width: "100%",
  textAlign: "left",
  background: "transparent",
  border: "1px solid transparent",
  color: t.text,
  cursor: "pointer",
  padding: "0.2rem 0.4rem",
  fontFamily: t.fontMono,
  fontSize: 11.5,
  borderRadius: 4,
};

function ArgField({
  arg, value, onChange, nodeOptions, listId, showError,
}: {
  arg: NexusSyntaxArg;
  value: string;
  onChange: (v: string) => void;
  nodeOptions: NexusNodeOption[];
  listId: string;
  showError: boolean;
}) {
  const error = showError ? validateArg(arg, value) : null;
  let control;
  if (arg.kind === "choice") {
    control = (
      <select className="input mono" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">— elige —</option>
        {arg.choices.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    );
  } else if (arg.kind === "onoff") {
    control = (
      <span className="seg">
        {([["ON", arg.on_value], ["OFF", arg.off_value]] as const).map(([label, wire]) => (
          <button key={label} type="button" className={value === wire ? "on" : ""}
            title={`Se envía ${wire}`} onClick={() => onChange(wire)}>{label}</button>
        ))}
      </span>
    );
  } else if (arg.kind === "node") {
    control = (
      <>
        <input className="input mono" list={listId} placeholder={arg.placeholder} value={value}
          onChange={(e) => onChange(e.target.value)} />
        <datalist id={listId}>
          {nodeOptions.map((n) => <option key={n.node_id} value={n.node_id}>{n.label}</option>)}
        </datalist>
      </>
    );
  } else {
    control = (
      <input
        className="input mono"
        inputMode={arg.kind === "number" ? "numeric" : undefined}
        placeholder={arg.placeholder || (arg.min !== null && arg.max !== null ? `${arg.min}–${arg.max}` : "")}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 11.5, color: t.textDim }}>
      <span>
        {arg.label}
        {arg.optional && <span style={{ color: t.textFaint }}> (opcional)</span>}
      </span>
      {control}
      {arg.hint && <span style={{ color: t.textFaint, fontSize: 10.5 }}>{arg.hint}</span>}
      {error && <span style={{ color: t.crit, fontSize: 10.5 }}>{error}</span>}
    </label>
  );
}

/** Asistente del catálogo; `initialName`/`initialVariantLabel` lo abren ya
 * posicionado en un comando y variante (botones grandes de acciones rápidas). */
export function NexusCatalogWizard({
  catalog, hidden, onSelect, onClose, nodeOptions, initialName = null, initialVariantLabel,
}: {
  catalog: NexusCatalogEntryOut[];
  hidden: Set<string>;
  onSelect: (name: string, args: string[]) => void;
  onClose: () => void;
  nodeOptions: NexusNodeOption[];
  initialName?: string | null;
  initialVariantLabel?: string;
}) {
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<string | null>(initialName);
  const [variantIdx, setVariantIdx] = useState(() => {
    const found = catalog.find((e) => e.name === initialName)?.syntax.findIndex((v) => v.label === initialVariantLabel);
    return found && found > 0 ? found : 0;
  });
  const [values, setValues] = useState<Record<string, string>>({});
  const [freeArgs, setFreeArgs] = useState("");
  const [touched, setTouched] = useState(false);

  const grouped = useMemo(() => {
    const q = filter.trim().toUpperCase();
    const entries = catalog.filter(
      (e) => !hidden.has(e.name)
        && (!q || e.name.includes(q) || e.aliases.some((a) => a.includes(q))
          || e.description.toUpperCase().includes(q)),
    );
    const byCat = new Map<string, NexusCatalogEntryOut[]>();
    for (const e of entries) byCat.set(e.category, [...(byCat.get(e.category) ?? []), e]);
    return CATEGORY_ORDER.filter((c) => byCat.has(c)).map((c) => [c, byCat.get(c)!] as const);
  }, [catalog, filter, hidden]);

  const entry = catalog.find((e) => e.name === selected) ?? null;
  const variant: NexusSyntaxVariant | null = entry?.syntax[variantIdx] ?? null;

  const pick = (name: string) => {
    setSelected(name);
    setVariantIdx(0);
    setValues({});
    setFreeArgs("");
    setTouched(false);
  };

  const errors = variant
    ? variant.args.map((a) => validateArg(a, values[a.name] ?? "")).filter(Boolean)
    : [];
  const args = variant
    ? assembleArgs(variant, values)
    : freeArgs.trim() ? freeArgs.trim().split(/\s+/) : [];
  const preview = entry ? ["/nexus", entry.name, ...args].join(" ") : "";

  const apply = () => {
    if (!entry) return;
    if (errors.length) { setTouched(true); return; }
    onSelect(entry.name, args);
    onClose();
  };

  return (
    <Modal title="Catálogo de comandos Nexus" onClose={onClose} width="min(920px, 96vw)">
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "stretch" }}>
        {/* Izquierda: elegir comando */}
        <div style={{ flex: "1 1 260px", minWidth: 240, maxWidth: 320 }}>
          <input
            className="input"
            autoFocus
            style={{ width: "100%", marginBottom: 6, boxSizing: "border-box" }}
            placeholder="Buscar por nombre, alias o descripción…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <div style={{ maxHeight: "56vh", overflowY: "auto" }}>
            {grouped.length === 0 && (
              <div style={{ color: t.textFaint, fontSize: 11.5 }}>Sin coincidencias.</div>
            )}
            {grouped.map(([category, entries]) => (
              <details key={category} open={filter.trim() !== "" || entries.some((e) => e.name === selected)}>
                <summary style={{ cursor: "pointer", fontSize: 11, color: t.textDim, padding: "0.2rem 0" }}>
                  {CATEGORY_LABEL[category] ?? category}{" "}
                  <span style={{ color: t.textFaint }}>({entries.length})</span>
                </summary>
                {entries.map((e) => (
                  <button
                    key={e.name}
                    style={{
                      ...listBtn,
                      background: e.name === selected ? t.surface2 : "transparent",
                      borderColor: e.name === selected ? t.accent : "transparent",
                    }}
                    onClick={() => pick(e.name)}
                  >
                    <span>{e.name}</span>
                    <span style={{ display: "flex", gap: 4, fontSize: 9.5 }}>
                      {e.syntax.length > 0 && <span style={{ color: t.accent }} title="Con asistente">●</span>}
                      {e.mutation !== "never" && <span style={{ color: t.textFaint }}>muta</span>}
                      {e.destructive && <span style={{ color: t.crit }}>⚠</span>}
                    </span>
                  </button>
                ))}
              </details>
            ))}
          </div>
          <div style={{ color: t.textFaint, fontSize: 10.5, marginTop: 6 }}>
            <span style={{ color: t.accent }}>●</span> = el asistente te guía con sus opciones.
          </div>
        </div>

        {/* Derecha: configurar */}
        <div style={{ flex: "2 1 360px", minWidth: 300, display: "flex", flexDirection: "column", gap: 10 }}>
          {!entry && (
            <div style={{ color: t.textFaint, fontSize: 12.5, padding: "1.5rem 0.5rem" }}>
              Elige un comando de la lista. Si tiene asistente, te mostrará sus variantes y los campos
              que pide cada una; si no, podrás escribir los argumentos a mano.
            </div>
          )}
          {entry && (
            <>
              <div>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                  <strong className="mono" style={{ fontSize: 15 }}>{entry.name}</strong>
                  {entry.aliases.length > 0 && (
                    <span style={{ color: t.textFaint, fontSize: 11 }}>alias: {entry.aliases.join(", ")}</span>
                  )}
                </div>
                <p style={{ color: t.textDim, fontSize: 12, margin: "4px 0" }}>
                  {entry.description || "Sin descripción documentada."}
                </p>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", fontSize: 10.5 }}>
                  <span style={{ color: entry.mutation === "never" ? t.textFaint : t.accent }}>
                    {entry.mutation === "never" ? "consulta" : entry.mutation === "with_args" ? "consulta o cambio según argumentos" : "modifica el nodo"}
                  </span>
                  {entry.destructive && <span style={{ color: t.crit }}>⚠ destructivo</span>}
                  {entry.busy_seconds > 0 && <span style={{ color: t.warn }}>ocupa el nodo {entry.busy_seconds}s</span>}
                  {entry.broadcast_forbidden && <span style={{ color: t.textFaint }}>🚫 no se puede enviar por difusión</span>}
                </div>
              </div>

              {entry.syntax.length > 0 ? (
                <>
                  <div>
                    <div style={{ color: t.textFaint, fontSize: 10.5, marginBottom: 4 }}>¿QUÉ QUIERES HACER?</div>
                    <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                      {entry.syntax.map((v, i) => (
                        <button
                          key={v.label}
                          style={{
                            ...chip,
                            borderColor: i === variantIdx ? t.accent : t.border,
                            color: i === variantIdx ? t.accent : t.text,
                          }}
                          onClick={() => { setVariantIdx(i); setValues({}); setTouched(false); }}
                        >
                          {v.label}
                          {v.verified && <span style={{ color: t.ok, marginLeft: 4 }} title="Probado en hardware real">✓</span>}
                        </button>
                      ))}
                    </div>
                  </div>
                  {variant && (
                    <>
                      <div style={{ fontSize: 10.5, color: variant.verified ? t.ok : t.textFaint }}>
                        {variant.verified
                          ? "✓ Verificado en hardware real"
                          : "Sintaxis según el manual v2.8.006, sin probar en campo"}
                      </div>
                      {variant.note && (
                        <div style={{ color: t.textDim, fontSize: 11.5 }}>ⓘ {variant.note}</div>
                      )}
                      {variant.args.length > 0 && (
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 10 }}>
                          {variant.args.map((a) => (
                            <ArgField
                              key={`${variantIdx}-${a.name}`}
                              arg={a}
                              value={values[a.name] ?? ""}
                              onChange={(v) => setValues((cur) => ({ ...cur, [a.name]: v }))}
                              nodeOptions={nodeOptions}
                              listId="nexus-wizard-nodes"
                              showError={touched}
                            />
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </>
              ) : (
                <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 11.5, color: t.textDim }}>
                  <span>Argumentos (opcional, separados por espacio)</span>
                  <input className="input mono" value={freeArgs} onChange={(e) => setFreeArgs(e.target.value)}
                    placeholder="Este comando aún no tiene asistente: escribe los argumentos tal cual el manual" />
                </label>
              )}

              <div className="panel" style={{ padding: "0.5rem 0.7rem" }}>
                <div style={{ color: t.textFaint, fontSize: 10.5 }}>
                  {errors.length ? "INCOMPLETO — FALTAN CAMPOS" : "SE ENVIARÁ"}
                </div>
                <div className="mono" style={{ fontSize: 13, wordBreak: "break-all", opacity: errors.length ? 0.5 : 1 }}>
                  {preview}
                </div>
              </div>

              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <button className="btn" onClick={apply}>Usar en la consola</button>
                <span style={{ color: t.textFaint, fontSize: 10.5 }}>
                  Solo rellena el formulario; sigues previsualizando y confirmando antes de enviar.
                </span>
              </div>
            </>
          )}
        </div>
      </div>
    </Modal>
  );
}

/**
 * Botón «Catálogo de comandos» que abre el asistente interactivo
 * (`GET /nexus/catalog`, ~180 comandos): lista por categorías a la izquierda
 * y, a la derecha, las variantes de cada comando con sus campos guiados
 * (selectores, ON/OFF, rangos, nodos) y la vista previa del texto exacto.
 * Los comandos sin `syntax` modelada caen a texto libre. Elegir uno solo
 * rellena nombre y argumentos del formulario del llamante — nunca envía
 * nada: sigue habiendo que previsualizar y confirmar.
 */
export function NexusCatalogBrowser({
  onSelect,
  nodeOptions = [],
}: {
  onSelect: (name: string, args: string[]) => void;
  nodeOptions?: NexusNodeOption[];
}) {
  const [open, setOpen] = useState(false);
  const catalog = useQuery({ queryKey: ["nexus-catalog"], queryFn: fetchNexusCatalog });
  const settings = useQuery({ queryKey: ["nexus-settings"], queryFn: fetchNexusSettings, enabled: open });
  const hidden = useMemo(() => new Set(settings.data?.hidden_commands ?? []), [settings.data]);

  return (
    <>
      <button className="btn ghost" onClick={() => setOpen(true)}>
        📖 Catálogo de comandos{catalog.data ? ` (${catalog.data.length - hidden.size})` : ""}
      </button>
      {open && catalog.data && (
        <NexusCatalogWizard
          catalog={catalog.data}
          hidden={hidden}
          onSelect={onSelect}
          onClose={() => setOpen(false)}
          nodeOptions={nodeOptions}
        />
      )}
      {open && !catalog.data && (
        <Modal title="Catálogo de comandos Nexus" onClose={() => setOpen(false)}>
          <div style={{ color: t.textFaint, fontSize: 12 }}>
            {catalog.isError ? "No se pudo cargar el catálogo." : "Cargando…"}
          </div>
        </Modal>
      )}
    </>
  );
}

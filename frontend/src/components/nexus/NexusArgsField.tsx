export interface NexusNodeOption {
  node_id: string;
  label: string;
}

// Comandos confirmados por captura real (ver docs/design/nexus-control.md
// §0.9/§0.10) cuyo ÚNICO argumento es un id de nodo — el resto del
// catálogo sigue siendo texto libre a propósito (§ catalog.py: "los
// argumentos viajan como tokens libres, el firmware los valida"; esto es
// SOLO una comodidad de UI para los pocos casos ya conocidos, no un
// modelado nuevo de sintaxis). FFAV/FIGNORE/FUNFAV/FUNIGNORE son las
// variantes "forzadas" de FAV/IGNORE/UNFAV/UNIGNORE (catalog.py, mismo
// patrón de nombre) — mismo único argumento.
const ID_ARG_COMMANDS = new Set([
  "FAV", "UNFAV", "IGNORE", "UNIGNORE",
  "FFAV", "FIGNORE", "FUNFAV", "FUNIGNORE",
]);

// Comandos con subverbo + id opcional (ZH ADD/DEL <id>, ZH LIST sin id;
// WATCH ADD/DEL/STATS <id>, WATCH LIST sin id).
const SUBVERB_ID_COMMANDS: Record<string, { value: string; needsId: boolean }[]> = {
  ZH: [
    { value: "ADD", needsId: true },
    { value: "DEL", needsId: true },
    { value: "LIST", needsId: false },
  ],
  WATCH: [
    { value: "ADD", needsId: true },
    { value: "DEL", needsId: true },
    { value: "LIST", needsId: false },
    { value: "STATS", needsId: true },
  ],
};

const idInputStyle = { width: 160 };

/**
 * Editor de argumentos consciente de los pocos comandos con forma conocida
 * (pedido explícito del usuario: "si quiero hacer un ignore, que pueda
 * escribir el id directamente" — en vez de recordar que hay que teclear
 * `!e53626b0` en una caja de texto genérica sin ninguna pista). Para
 * cualquier otro comando, cae al campo de texto libre de siempre.
 */
export function NexusArgsField({
  command,
  args,
  onChange,
  nodeOptions,
}: {
  command: string;
  args: string[];
  onChange: (args: string[]) => void;
  nodeOptions: NexusNodeOption[];
}) {
  const normalized = command.trim().toUpperCase();
  const datalistId = "nexus-args-node-options";

  const idDatalist = (
    <datalist id={datalistId}>
      {nodeOptions.map((n) => (
        <option key={n.node_id} value={n.node_id}>{n.label}</option>
      ))}
    </datalist>
  );

  if (ID_ARG_COMMANDS.has(normalized)) {
    return (
      <>
        <input
          className="input mono"
          style={idInputStyle}
          placeholder="!xxxxxxxx (id de nodo)"
          value={args[0] ?? ""}
          onChange={(e) => onChange([e.target.value])}
          list={datalistId}
        />
        {idDatalist}
      </>
    );
  }

  const subverbs = SUBVERB_ID_COMMANDS[normalized];
  if (subverbs) {
    const verb = args[0] ?? subverbs[0].value;
    const needsId = subverbs.find((v) => v.value === verb)?.needsId ?? false;
    return (
      <>
        <select
          className="input"
          style={{ width: 90 }}
          value={verb}
          onChange={(e) => {
            const nextNeedsId = subverbs.find((v) => v.value === e.target.value)?.needsId ?? false;
            onChange(nextNeedsId ? [e.target.value, args[1] ?? ""] : [e.target.value]);
          }}
        >
          {subverbs.map((v) => (
            <option key={v.value} value={v.value}>{v.value}</option>
          ))}
        </select>
        {needsId && (
          <input
            className="input mono"
            style={idInputStyle}
            placeholder="!xxxxxxxx (id de nodo)"
            value={args[1] ?? ""}
            onChange={(e) => onChange([verb, e.target.value])}
            list={datalistId}
          />
        )}
        {needsId && idDatalist}
      </>
    );
  }

  return (
    <input
      className="input mono"
      style={{ width: 200 }}
      placeholder="argumentos (espacio)"
      value={args.join(" ")}
      onChange={(e) => onChange(e.target.value.trim() ? e.target.value.trim().split(/\s+/) : [])}
    />
  );
}

import { useMemo, useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchNexusCatalog, fetchNexusSettings, type NexusCatalogEntryOut } from "../../api/client";
import { t } from "../../tokens";

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

const btn: CSSProperties = {
  background: "transparent",
  border: `1px solid ${t.border}`,
  color: t.text,
  borderRadius: 4,
  cursor: "pointer",
  fontSize: 11,
  padding: "0.1rem 0.5rem",
};

const rowBtn: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  width: "100%",
  textAlign: "left",
  background: "transparent",
  border: "none",
  color: t.text,
  cursor: "pointer",
  padding: "0.2rem 0.3rem",
  fontFamily: t.fontMono,
  fontSize: 12,
  borderRadius: 4,
};

/**
 * Explorador del catálogo completo (`GET /nexus/catalog`, ~180 comandos) —
 * pedido explícito del usuario: en vez de escribir el nombre de memoria,
 * poder ver y elegir entre TODOS los comandos disponibles, agrupados por
 * categoría (misma categorización de `catalog.py`, §3 del manual). Elegir
 * uno solo rellena el nombre del comando en el formulario del llamante —
 * nunca envía nada por sí mismo, sigue habiendo que previsualizar y
 * confirmar como con cualquier comando tecleado a mano.
 */
export function NexusCatalogBrowser({ onSelect }: { onSelect: (name: string) => void }) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const catalog = useQuery({ queryKey: ["nexus-catalog"], queryFn: fetchNexusCatalog, enabled: open });
  // Ajustes (ADR 0027 §13): hidden_commands filtra el explorador (nunca el
  // catálogo real del backend, solo lo que se OFRECE aquí — el comando
  // sigue siendo válido si se escribe a mano) y catalog_collapsed_default
  // decide si las categorías empiezan plegadas o abiertas.
  const settings = useQuery({ queryKey: ["nexus-settings"], queryFn: fetchNexusSettings, enabled: open });
  const hidden = useMemo(() => new Set(settings.data?.hidden_commands ?? []), [settings.data]);
  const collapsedDefault = settings.data?.catalog_collapsed_default ?? false;

  const grouped = useMemo(() => {
    const entries = (catalog.data ?? []).filter((e) => !hidden.has(e.name));
    const q = filter.trim().toUpperCase();
    const filtered = q
      ? entries.filter((e) => e.name.includes(q) || e.aliases.some((a) => a.includes(q)))
      : entries;
    const byCategory = new Map<string, NexusCatalogEntryOut[]>();
    for (const entry of filtered) {
      const list = byCategory.get(entry.category) ?? [];
      list.push(entry);
      byCategory.set(entry.category, list);
    }
    return CATEGORY_ORDER.filter((c) => byCategory.has(c)).map((c) => [c, byCategory.get(c)!] as const);
  }, [catalog.data, filter, hidden]);

  return (
    <div>
      <button style={btn} onClick={() => setOpen((v) => !v)}>
        {open
          ? "Cerrar catálogo ▴"
          : `Explorar catálogo (${catalog.data ? catalog.data.length - hidden.size : "…"}) ▾`}
      </button>
      {open && (
        <div
          style={{
            marginTop: 6,
            border: `1px solid ${t.borderSubtle}`,
            borderRadius: 6,
            background: t.surface2,
            maxHeight: 320,
            overflowY: "auto",
            padding: "0.4rem 0.5rem",
          }}
        >
          <input
            autoFocus
            placeholder="Filtrar por nombre o alias…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{
              width: "100%",
              background: t.bg,
              border: `1px solid ${t.border}`,
              color: t.text,
              borderRadius: 4,
              padding: "0.2rem 0.4rem",
              fontSize: 12,
              marginBottom: 6,
              boxSizing: "border-box",
            }}
          />
          {catalog.isLoading && <div style={{ color: t.textFaint, fontSize: 11.5 }}>Cargando…</div>}
          {grouped.length === 0 && !catalog.isLoading && (
            <div style={{ color: t.textFaint, fontSize: 11.5 }}>Sin coincidencias.</div>
          )}
          {grouped.map(([category, entries]) => (
            <details key={category} open={!collapsedDefault ? grouped.length <= 3 || filter.trim() !== "" : filter.trim() !== ""}>
              <summary style={{ cursor: "pointer", fontSize: 11, color: t.textDim, padding: "0.15rem 0" }}>
                {CATEGORY_LABEL[category] ?? category} <span style={{ color: t.textFaint }}>({entries.length})</span>
              </summary>
              <div style={{ display: "flex", flexDirection: "column" }}>
                {entries.map((entry) => (
                  <button
                    key={entry.name}
                    style={rowBtn}
                    title={entry.aliases.length ? `alias: ${entry.aliases.join(", ")}` : undefined}
                    onClick={() => {
                      onSelect(entry.name);
                      setOpen(false);
                    }}
                  >
                    <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {entry.name}
                    </span>
                    {entry.mutation === "never" ? (
                      <span style={{ fontSize: 9.5, color: t.textFaint }}>consulta</span>
                    ) : (
                      <span style={{ fontSize: 9.5, color: t.accent }}>muta</span>
                    )}
                    {entry.destructive && <span style={{ fontSize: 9.5, color: t.crit }}>⚠ destructivo</span>}
                    {entry.busy_seconds > 0 && (
                      <span style={{ fontSize: 9.5, color: t.warn }}>{entry.busy_seconds}s</span>
                    )}
                    {entry.broadcast_forbidden && (
                      <span style={{ fontSize: 9.5, color: t.textFaint }} title="Bloqueado en difusión/grupo">
                        🚫difusión
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}

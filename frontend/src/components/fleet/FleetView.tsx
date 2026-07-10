import { useMemo } from "react";
import {
  activeGatewayCount,
  type GatewayOut,
  type GroupOut,
  type NodeFilterParams,
  type NodeSummaryOut,
  type TagOut,
} from "../../api/client";

/**
 * Flota (identidad v0.8): sustituye a la vista "Nodos" (tabla HTML + barra de
 * selects). Un roster de operación: KPIs arriba, barra de mando con filtros
 * segmentados, filas densas con instrumentos (presencia, batería como
 * medidor, SNR como barras de señal) y una barra de armado de lotes que solo
 * existe cuando hay selección. Cero lógica nueva: mismos filtros M1.2,
 * misma selección M2, mismo Inspector global al hacer clic.
 */

const GRID = "20px 20px 14px minmax(140px,1.5fr) 92px minmax(80px,1fr) 120px 76px minmax(90px,120px) 70px 26px";

function relTime(iso: string | null): string {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

function Battery({ level }: { level: number | null | undefined }) {
  if (level == null) return <span style={{ color: "var(--text-faint)" }}>—</span>;
  if (level > 100) {
    return <span className="meter" style={{ color: "var(--ok)" }}>⚡ ext</span>;
  }
  const color = level <= 20 ? "var(--crit)" : level <= 50 ? "var(--warn)" : "var(--ok)";
  return (
    <span className="meter">
      <span className="track">
        <span className="fill" style={{ width: `${level}%`, background: color }} />
      </span>
      <span style={{ color }}>{level}%</span>
    </span>
  );
}

function Signal({ snr }: { snr: number | null }) {
  if (snr == null) return <span style={{ color: "var(--text-faint)" }}>—</span>;
  const bars = snr > 5 ? 4 : snr > 0 ? 3 : snr > -7 ? 2 : snr > -15 ? 1 : 0;
  const heights = [4, 7, 10, 12];
  return (
    <span
      className={`sigbars${bars <= 2 ? " weak" : ""}`}
      title={`SNR ${snr} dB`}
      style={{ marginRight: 5 }}
    >
      {heights.map((h, i) => (
        <i key={i} className={i < bars ? "on" : undefined} style={{ height: h }} />
      ))}
    </span>
  );
}

export function FleetView({
  summaries,
  allSummaries,
  loading,
  error,
  filters,
  onFiltersChange,
  tags,
  groups,
  gateways,
  hwModels,
  selected,
  focusId,
  onSelect,
  onToggleFavorite,
  onToggleIgnored,
  checkedIds,
  onCheckedChange,
  onCreateBatch,
}: {
  summaries: NodeSummaryOut[];
  allSummaries: NodeSummaryOut[];
  loading: boolean;
  error: boolean;
  filters: NodeFilterParams;
  onFiltersChange: (f: NodeFilterParams) => void;
  tags: TagOut[];
  groups: GroupOut[];
  gateways: GatewayOut[];
  hwModels: string[];
  selected: string | null;
  focusId: string | null;
  onSelect: (id: string) => void;
  onToggleFavorite: (id: string, value: boolean) => void;
  onToggleIgnored: (id: string, value: boolean) => void;
  checkedIds: Set<string>;
  onCheckedChange: (ids: Set<string>) => void;
  onCreateBatch: () => void;
}) {
  const set = (patch: NodeFilterParams) => onFiltersChange({ ...filters, ...patch });
  const hasFilters = Object.values(filters).some((v) => v !== undefined && v !== "" && v !== false);

  const online = summaries.filter((s) => s.node.online).length;
  const lowBattery = useMemo(
    () =>
      summaries.filter((s) => {
        const b = s.last_device_telemetry?.battery_level;
        return b != null && b <= 20 && b <= 100;
      }).length,
    [summaries],
  );
  const favCount = allSummaries.filter((s) => s.node.is_favorite).length;

  const toggleChecked = (id: string) => {
    const next = new Set(checkedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onCheckedChange(next);
  };
  const allVisibleChecked =
    summaries.length > 0 && summaries.every((s) => checkedIds.has(s.node.node_id));

  return (
    <div className="ws">
      {/* Constantes de la flota */}
      <div className="kpis">
        <div className="kpi">
          <div className="v">{summaries.length}</div>
          <div className="k">Nodos{hasFilters ? " (filtro)" : ""}</div>
        </div>
        <div className="kpi">
          <div className="v" style={{ color: "var(--ok)" }}>{online}</div>
          <div className="k">En línea</div>
        </div>
        <div className="kpi">
          <div className="v" style={{ color: summaries.length - online > 0 ? "var(--text-dim)" : "var(--text)" }}>
            {summaries.length - online}
          </div>
          <div className="k">Offline</div>
        </div>
        <div className="kpi">
          <div className="v" style={{ color: lowBattery > 0 ? "var(--warn)" : "var(--text)" }}>{lowBattery}</div>
          <div className="k">Batería ≤20%</div>
        </div>
        <div className="kpi">
          <div className="v">{favCount}</div>
          <div className="k">Favoritos</div>
        </div>
        <div className="kpi">
          <div className="v" style={{ color: checkedIds.size > 0 ? "var(--accent)" : "var(--text-faint)" }}>
            {checkedIds.size}
          </div>
          <div className="k">Armados p/ lote</div>
        </div>
      </div>

      {/* Barra de mando: búsqueda + filtros M1.2 */}
      <div className="toolbar">
        <input
          className="input"
          style={{ minWidth: 200, fontFamily: "var(--font-mono)" }}
          placeholder="buscar nombre o !id…"
          value={filters.q ?? ""}
          onChange={(e) => set({ q: e.target.value || undefined })}
        />
        <span className="seg" role="group" aria-label="Estado">
          {([
            ["", "todos"],
            ["true", "online"],
            ["false", "offline"],
          ] as const).map(([v, label]) => (
            <button
              key={label}
              className={(filters.online === undefined ? "" : String(filters.online)) === v ? "on" : undefined}
              onClick={() => set({ online: v === "" ? undefined : v === "true" })}
            >
              {label}
            </button>
          ))}
        </span>
        <button
          className={`btn ghost${filters.favorite ? " primary" : ""}`}
          style={filters.favorite ? { color: "var(--warn)", borderColor: "var(--warn)", background: "var(--warn-tint)" } : undefined}
          onClick={() => set({ favorite: filters.favorite ? undefined : true })}
        >
          ★ favoritos
        </button>
        <span className="sep" />
        <select className="input" value={filters.hw_model ?? ""} onChange={(e) => set({ hw_model: e.target.value || undefined })}>
          <option value="">hardware</option>
          {hwModels.map((h) => (
            <option key={h} value={h}>{h}</option>
          ))}
        </select>
        <select className="input" value={filters.tag ?? ""} onChange={(e) => set({ tag: e.target.value || undefined })}>
          <option value="">etiqueta</option>
          {tags.map((t) => (
            <option key={t.id} value={t.name}>{t.name}</option>
          ))}
        </select>
        <select
          className="input"
          value={filters.group_id ?? ""}
          onChange={(e) => set({ group_id: e.target.value ? Number(e.target.value) : undefined })}
        >
          <option value="">grupo</option>
          {groups.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name} ({g.member_count})
            </option>
          ))}
        </select>
        <select className="input" value={filters.gateway_id ?? ""} onChange={(e) => set({ gateway_id: e.target.value || undefined })}>
          <option value="">pasarela</option>
          {gateways.map((g) => (
            <option key={g.gateway_id} value={g.gateway_id}>{g.name ?? g.gateway_id}</option>
          ))}
        </select>
        <label className="microlabel" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          bat &lt;
          <input
            className="input"
            style={{ width: 52 }}
            type="number"
            min={1}
            max={101}
            value={filters.battery_below ?? ""}
            onChange={(e) => set({ battery_below: e.target.value ? Number(e.target.value) : undefined })}
          />
          %
        </label>
        <button
          className={`btn ghost${filters.include_ignored ? " on" : ""}`}
          style={filters.include_ignored ? { color: "var(--text)", borderColor: "var(--border)" } : undefined}
          onClick={() => set({ include_ignored: filters.include_ignored ? undefined : true })}
          title="Mostrar también los nodos ignorados"
        >
          {filters.include_ignored ? "◉" : "○"} ignorados
        </button>
        {hasFilters && (
          <button className="btn ghost" onClick={() => onFiltersChange({})}>
            ✕ limpiar
          </button>
        )}
      </div>

      {/* Roster */}
      <div className="panel" style={{ flex: 1, border: "none" }}>
        <div className="ws-scroll">
          <div className="roster-head" style={{ gridTemplateColumns: GRID }}>
            <span>
              <input
                type="checkbox"
                checked={allVisibleChecked}
                onChange={() => {
                  const next = new Set(checkedIds);
                  for (const s of summaries) {
                    if (allVisibleChecked) next.delete(s.node.node_id);
                    else next.add(s.node.node_id);
                  }
                  onCheckedChange(next);
                }}
                title="Armar/desarmar todos los visibles"
              />
            </span>
            <span />
            <span />
            <span>Nodo</span>
            <span>ID</span>
            <span>Etiquetas</span>
            <span>Batería</span>
            <span>Señal</span>
            <span>Pasarela</span>
            <span>Visto</span>
            <span />
          </div>
          {loading && <div className="empty">Cargando flota…</div>}
          {error && <div className="empty" style={{ color: "var(--crit)" }}>Error consultando la API.</div>}
          {!loading && summaries.length === 0 && (
            <div className="empty">Ningún nodo coincide con los filtros actuales.</div>
          )}
          {summaries.map((summary) => {
            const { node, last_device_telemetry, tags: nodeTags } = summary;
            const gwCount = activeGatewayCount(summary);
            const cls = [
              "roster-row",
              focusId === node.node_id ? "focus" : selected === node.node_id ? "sel" : "",
              node.is_ignored ? "dim" : "",
            ]
              .filter(Boolean)
              .join(" ");
            return (
              <div
                key={node.node_id}
                className={cls}
                style={{ gridTemplateColumns: GRID }}
                onClick={() => onSelect(node.node_id)}
              >
                <span onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={checkedIds.has(node.node_id)}
                    onChange={() => toggleChecked(node.node_id)}
                  />
                </span>
                <span
                  title={node.is_favorite ? "Quitar de favoritos" : "Marcar favorito"}
                  style={{ cursor: "pointer", color: node.is_favorite ? "var(--warn)" : "var(--text-faint)" }}
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggleFavorite(node.node_id, !node.is_favorite);
                  }}
                >
                  {node.is_favorite ? "★" : "☆"}
                </span>
                <span
                  className={`presence ${node.online ? "on" : "off"}`}
                  title={node.online ? "En línea" : "Offline"}
                >
                  {node.online ? "●" : "○"}
                </span>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  <strong>{node.short_name ?? "?"}</strong>{" "}
                  <span style={{ color: "var(--text-dim)" }}>{node.long_name ?? ""}</span>
                  {node.is_ignored && <span style={{ color: "var(--text-faint)" }}> · ignorado</span>}
                </span>
                <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>{node.node_id}</span>
                <span style={{ overflow: "hidden", whiteSpace: "nowrap" }}>
                  {nodeTags.map((tag) => (
                    <span
                      key={tag.id}
                      className="chip"
                      style={{ marginRight: 4, borderColor: tag.color ?? "var(--border)", color: tag.color ?? "var(--text-dim)" }}
                    >
                      {tag.name}
                    </span>
                  ))}
                </span>
                <span>
                  <Battery level={last_device_telemetry?.battery_level} />
                </span>
                <span>
                  <Signal snr={node.snr} />
                  {node.snr != null && (
                    <span className="mono" style={{ fontSize: 10.5, color: "var(--text-dim)" }}>
                      {node.snr}
                    </span>
                  )}
                </span>
                <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {node.gateway_id ?? "—"}
                  {gwCount > 1 && (
                    <span className="chip" style={{ marginLeft: 5, color: "var(--accent)", borderColor: "var(--accent)" }} title={`Oído por ${gwCount} pasarelas`}>
                      🛰{gwCount}
                    </span>
                  )}
                </span>
                <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>
                  {relTime(node.last_seen_at)}
                </span>
                <span
                  title={node.is_ignored ? "Dejar de ignorar" : "Ignorar nodo"}
                  style={{ cursor: "pointer", color: "var(--text-faint)" }}
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggleIgnored(node.node_id, !node.is_ignored);
                  }}
                >
                  {node.is_ignored ? "🚫" : "👁"}
                </span>
              </div>
            );
          })}
        </div>

        {/* Barra de armado: solo existe cuando hay selección */}
        {checkedIds.size > 0 && (
          <div
            className="toolbar"
            style={{ borderTop: "1px solid var(--accent)", borderBottom: "none", background: "var(--surface-2)" }}
          >
            <span className="microlabel" style={{ color: "var(--accent)" }}>
              {checkedIds.size} nodo{checkedIds.size !== 1 ? "s" : ""} armado{checkedIds.size !== 1 ? "s" : ""}
            </span>
            <button
              className="btn ghost"
              onClick={() => onCheckedChange(new Set([...checkedIds, ...summaries.map((s) => s.node.node_id)]))}
            >
              + visibles
            </button>
            <button
              className="btn ghost"
              onClick={() => {
                const next = new Set(checkedIds);
                for (const s of summaries) {
                  if (next.has(s.node.node_id)) next.delete(s.node.node_id);
                  else next.add(s.node.node_id);
                }
                onCheckedChange(next);
              }}
            >
              invertir
            </button>
            <button
              className="btn ghost"
              onClick={() =>
                onCheckedChange(
                  new Set([
                    ...checkedIds,
                    ...allSummaries.filter((s) => s.node.is_favorite).map((s) => s.node.node_id),
                  ]),
                )
              }
            >
              + favoritos
            </button>
            <button className="btn ghost" onClick={() => onCheckedChange(new Set())}>
              desarmar todo
            </button>
            <span style={{ marginLeft: "auto" }} />
            <button className="btn primary" onClick={onCreateBatch}>
              ▶ Crear lote ({checkedIds.size})
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

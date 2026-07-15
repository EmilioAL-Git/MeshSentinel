import { useMemo } from "react";
import {
  type AlertOut,
  type GatewayOut,
  type GroupOut,
  type MultiGatewayStatsOut,
  type NodeFilterParams,
  type NodeSummaryOut,
  type TagOut,
} from "../../api/client";
import { usePersistedState } from "../../hooks/usePersistedState";
import { AddToGroupMenu } from "./AddToGroupMenu";
import { AssignNodeTypeMenu } from "./AssignNodeTypeMenu";
import { ColumnPicker } from "./ColumnPicker";
import { FleetBlocks } from "./FleetBlocks";
import { GroupBar } from "./GroupBar";
import { computeFleetGroupMetrics } from "./groupStats";
import { DEFAULT_FLEET_COLUMNS, FLEET_COLUMNS, FleetRow, buildFleetGrid, type FleetColumnId } from "./instruments";

/**
 * Flota (fase "Flota orientada a grupos", v0.8.x): con grupo activo deja de
 * ser una lista plana — es la representación operativa de ese grupo, en
 * bloques por categoría (§ FleetBlocks) con su propia banda de estado
 * (§ GroupBar). Sin grupo activo ("Toda la red"), se comporta exactamente
 * como hasta ahora: roster plano, filtros M1.2 completos, misma selección
 * M2, mismo Inspector global al hacer clic. La taxonomía SOLO existe dentro
 * de un grupo — no tiene sentido clasificar miles de nodos ajenos.
 */

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
  gatewayNodeIds,
  activeGroup,
  groupGatewayStats,
  alerts,
  hwModels,
  selected,
  focusId,
  onSelect,
  onToggleFavorite,
  onToggleIgnored,
  checkedIds,
  onCheckedChange,
  onCreateBatch,
  lowBatteryThreshold,
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
  gatewayNodeIds: Set<string>;
  activeGroup: GroupOut | null;
  groupGatewayStats: MultiGatewayStatsOut | undefined;
  alerts: AlertOut[];
  hwModels: string[];
  selected: string | null;
  focusId: string | null;
  onSelect: (id: string) => void;
  onToggleFavorite: (id: string, value: boolean) => void;
  onToggleIgnored: (id: string, value: boolean) => void;
  checkedIds: Set<string>;
  onCheckedChange: (ids: Set<string>) => void;
  onCreateBatch: () => void;
  /** Umbral de batería baja de la red (thresholds del backend) — nunca un
   * valor hardcodeado aquí (hardening). */
  lowBatteryThreshold: number;
}) {
  const set = (patch: NodeFilterParams) => onFiltersChange({ ...filters, ...patch });
  const hasFilters = Object.values(filters).some((v) => v !== undefined && v !== "" && v !== false);
  const isGrouped = activeGroup != null;
  // Columnas del roster configurables (pedido del usuario): persistidas,
  // reutilizadas por el modo plano y por bloques (FleetBlocks) — misma
  // fila en ambos, ver instruments.tsx.
  const [visibleColumns, setVisibleColumns] = usePersistedState<FleetColumnId[]>("fleet.columns", DEFAULT_FLEET_COLUMNS);

  // Orden ESTABLE del roster (hardening): el backend ordena por
  // last_seen_at desc, que reordena filas bajo el cursor con cada refetch —
  // inaceptable en una tabla donde se arman lotes con checkboxes. Aquí se
  // ordena por nombre (desempate por id); la actividad se muestra como
  // indicador (columna "Visto" + pulso de recencia), nunca como criterio
  // de orden.
  const stableSummaries = useMemo(() => {
    const key = (s: NodeSummaryOut) =>
      (s.node.short_name ?? s.node.long_name ?? s.node.node_id).toLowerCase();
    return [...summaries].sort(
      (a, b) => key(a).localeCompare(key(b)) || a.node.node_id.localeCompare(b.node.node_id),
    );
  }, [summaries]);

  // Memoizados: con miles de nodos, recorrer `summaries`/`allSummaries` en
  // cada render (incl. los que no cambian ni datos ni selección) deja de
  // ser gratis.
  const online = useMemo(() => summaries.filter((s) => s.node.online).length, [summaries]);
  const lowBattery = useMemo(
    () =>
      summaries.filter((s) => {
        const b = s.last_device_telemetry?.battery_level;
        return b != null && b <= 100 && b < lowBatteryThreshold;
      }).length,
    [summaries, lowBatteryThreshold],
  );
  const favCount = useMemo(() => allSummaries.filter((s) => s.node.is_favorite).length, [allSummaries]);
  const groupMetrics = useMemo(() => computeFleetGroupMetrics(summaries, alerts), [summaries, alerts]);

  const toggleChecked = (id: string) => {
    const next = new Set(checkedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onCheckedChange(next);
  };
  const allVisibleChecked = useMemo(
    () => summaries.length > 0 && summaries.every((s) => checkedIds.has(s.node.node_id)),
    [summaries, checkedIds],
  );

  return (
    <div className="ws">
      {isGrouped && activeGroup && (
        <GroupBar
          group={activeGroup}
          metrics={groupMetrics}
          gatewayStats={groupGatewayStats}
          lowBatteryThreshold={lowBatteryThreshold}
        />
      )}

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
          <div className="k">Batería &lt;{lowBatteryThreshold}%</div>
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
        {/* El filtro manual de grupo queda oculto con grupo activo: ya está
            scopado por el selector global (App.tsx), mostrarlo aquí sería
            un segundo mecanismo redundante para lo mismo. */}
        {!isGrouped && (
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
        )}
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
        <span style={{ marginLeft: "auto" }} />
        <ColumnPicker visible={visibleColumns} onChange={setVisibleColumns} />
      </div>

      {/* Roster: bloques por categoría dentro de un grupo, lista plana en "Toda la red" */}
      <div className="panel" style={{ flex: 1, border: "none" }}>
        <div className="ws-scroll">
          {loading && <div className="empty">Cargando flota…</div>}
          {error && <div className="empty" style={{ color: "var(--crit)" }}>Error consultando la API.</div>}
          {!loading && summaries.length === 0 && (
            <div className="empty">Ningún nodo coincide con los filtros actuales.</div>
          )}
          {!loading && summaries.length > 0 && isGrouped && (
            <FleetBlocks
              summaries={stableSummaries}
              gatewayNodeIds={gatewayNodeIds}
              selected={selected}
              focusId={focusId}
              checkedIds={checkedIds}
              onSelect={onSelect}
              onToggleFavorite={onToggleFavorite}
              onToggleIgnored={onToggleIgnored}
              onCheckedChange={onCheckedChange}
              lowBatteryThreshold={lowBatteryThreshold}
              visibleColumns={visibleColumns}
            />
          )}
          {!loading && summaries.length > 0 && !isGrouped && (
            <>
              <RosterHeadWithSelectAll
                allVisibleChecked={allVisibleChecked}
                visibleColumns={visibleColumns}
                onToggleAll={() => {
                  const next = new Set(checkedIds);
                  for (const s of summaries) {
                    if (allVisibleChecked) next.delete(s.node.node_id);
                    else next.add(s.node.node_id);
                  }
                  onCheckedChange(next);
                }}
              />
              {stableSummaries.map((summary) => (
                <FleetRow
                  key={summary.node.node_id}
                  summary={summary}
                  selected={selected}
                  focusId={focusId}
                  checked={checkedIds.has(summary.node.node_id)}
                  onSelect={onSelect}
                  onToggleFavorite={onToggleFavorite}
                  onToggleIgnored={onToggleIgnored}
                  onToggleChecked={toggleChecked}
                  visibleColumns={visibleColumns}
                  gatewayNodeIds={gatewayNodeIds}
                  lowBatteryThreshold={lowBatteryThreshold}
                />
              ))}
            </>
          )}
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
            <AddToGroupMenu selectedIds={[...checkedIds]} groups={groups} allSummaries={allSummaries} />
            <AssignNodeTypeMenu selectedIds={[...checkedIds]} />
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

/** Cabecera plana con el checkbox "armar/desarmar todos" (solo modo "Toda la red"). */
function RosterHeadWithSelectAll({
  allVisibleChecked,
  onToggleAll,
  visibleColumns,
}: {
  allVisibleChecked: boolean;
  onToggleAll: () => void;
  visibleColumns: FleetColumnId[];
}) {
  return (
    <div className="roster-head" style={{ gridTemplateColumns: buildFleetGrid(visibleColumns) }}>
      <span>
        <input type="checkbox" checked={allVisibleChecked} onChange={onToggleAll} title="Armar/desarmar todos los visibles" />
      </span>
      <span />
      <span />
      <span>Nodo</span>
      <span>ID</span>
      {FLEET_COLUMNS.filter((c) => visibleColumns.includes(c.id)).map((c) => (
        <span key={c.id}>{c.label}</span>
      ))}
      <span />
    </div>
  );
}

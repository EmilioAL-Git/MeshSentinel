import { useMemo } from "react";
import type { NodeSummaryOut } from "../../api/client";
import { BlockAccordion } from "../shell/BlockAccordion";
import { CATEGORY_DEFS, groupByCategory } from "./classify";
import { FleetRow, RosterHead, type FleetColumnId } from "./instruments";

/**
 * Vista de bloques dentro de un grupo activo (fase "Flota orientada a
 * grupos"): primero categorías, después nodos — nunca una tabla plana.
 * Reutiliza `BlockAccordion` (plegado persistido por bloque, ya usado en el
 * StatusPanel del Centro desde v0.7) y `FleetRow` (misma fila, pixel a
 * pixel, que el modo "Toda la red").
 */
export function FleetBlocks({
  summaries,
  gatewayNodeIds,
  selected,
  focusId,
  checkedIds,
  onSelect,
  onToggleFavorite,
  onToggleIgnored,
  onCheckedChange,
  lowBatteryThreshold,
  visibleColumns,
}: {
  summaries: NodeSummaryOut[];
  gatewayNodeIds: Set<string>;
  selected: string | null;
  focusId: string | null;
  checkedIds: Set<string>;
  onSelect: (id: string) => void;
  onToggleFavorite: (id: string, value: boolean) => void;
  onToggleIgnored: (id: string, value: boolean) => void;
  onCheckedChange: (ids: Set<string>) => void;
  /** Umbral de batería baja (thresholds del backend, no hardcodeado). */
  lowBatteryThreshold?: number;
  visibleColumns: FleetColumnId[];
}) {
  const byCategory = useMemo(() => groupByCategory(summaries, gatewayNodeIds), [summaries, gatewayNodeIds]);

  const toggleChecked = (id: string) => {
    const next = new Set(checkedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onCheckedChange(next);
  };

  const toggleBlock = (items: NodeSummaryOut[], allChecked: boolean) => {
    const next = new Set(checkedIds);
    for (const s of items) {
      if (allChecked) next.delete(s.node.node_id);
      else next.add(s.node.node_id);
    }
    onCheckedChange(next);
  };

  return (
    <div>
      {CATEGORY_DEFS.map((def) => {
        const items = byCategory.get(def.id) ?? [];
        if (items.length === 0) return null;
        const allChecked = items.every((s) => checkedIds.has(s.node.node_id));
        return (
          <BlockAccordion
            key={def.id}
            id={`fleet-block.${def.id}`}
            title={def.label}
            icon={def.icon}
            count={items.length}
            action={
              <button
                className="btn ghost"
                style={{ fontSize: 10.5, padding: "0.15rem 0.5rem" }}
                onClick={(e) => {
                  e.stopPropagation();
                  toggleBlock(items, allChecked);
                }}
              >
                {allChecked ? "quitar todo" : "seleccionar todo"}
              </button>
            }
          >
            <RosterHead visibleColumns={visibleColumns} />
            {items.map((summary) => (
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
          </BlockAccordion>
        );
      })}
    </div>
  );
}

import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchGroups, type AlertOut, type GroupOut, type NodeSummaryOut, type OperationOut } from "../api/client";
import { usePersistedState } from "../hooks/usePersistedState";
import { useUrlNumber } from "../hooks/useUrlState";

/**
 * Grupo de trabajo activo: contexto global de MeshSentinel (fase de
 * infraestructura, sin comportamiento todavía). Un grupo deja de ser una
 * propiedad de un nodo para convertirse en el ámbito de trabajo de toda la
 * sesión — cualquier componente puede preguntar "¿hay un grupo activo?" con
 * `useActiveGroup()`, sin que su firma de props cambie hasta que de verdad
 * necesite actuar sobre ello. Reutiliza `groups`/`group_id` (M1.2) tal cual:
 * cero modelo de datos nuevo.
 */

interface GroupContextValue {
  activeGroupId: number | null;
  activeGroup: GroupOut | null;
  groups: GroupOut[];
  setActiveGroup: (groupId: number | null) => void;
  clearActiveGroup: () => void;
}

const GroupContext = createContext<GroupContextValue | null>(null);

export function GroupProvider({ children }: { children: ReactNode }) {
  // Mismo queryKey que App.tsx: TanStack Query comparte la caché, sin fetch duplicado.
  const groups = useQuery({ queryKey: ["groups"], queryFn: fetchGroups });
  // URLs compartibles (ADR 0026): la URL manda sobre la preferencia de sesión
  // cuando el parámetro `group` está presente; si no, cae a `localStorage`
  // (puesto de trabajo del operador entre sesiones sin enlace explícito).
  const [storedGroupId, setStoredGroupId] = usePersistedState<number | null>("activeGroupId", null);
  const [urlGroupId, setUrlGroupId] = useUrlNumber("group", null);
  const activeGroupId = urlGroupId ?? storedGroupId;

  const list = groups.data ?? [];
  const activeGroup = useMemo(
    () => (activeGroupId != null ? (list.find((g) => g.id === activeGroupId) ?? null) : null),
    [list, activeGroupId],
  );

  const setActiveGroup = useCallback(
    (groupId: number | null) => {
      setStoredGroupId(groupId);
      setUrlGroupId(groupId);
    },
    [setStoredGroupId, setUrlGroupId],
  );
  const clearActiveGroup = useCallback(() => setActiveGroup(null), [setActiveGroup]);

  const value = useMemo<GroupContextValue>(
    () => ({ activeGroupId, activeGroup, groups: list, setActiveGroup, clearActiveGroup }),
    [activeGroupId, activeGroup, list, setActiveGroup, clearActiveGroup],
  );

  return <GroupContext.Provider value={value}>{children}</GroupContext.Provider>;
}

/** Disponible desde cualquier componente bajo `<GroupProvider>` (toda la app). */
export function useActiveGroup(): GroupContextValue {
  const ctx = useContext(GroupContext);
  if (!ctx) throw new Error("useActiveGroup() requiere <GroupProvider> como ancestro");
  return ctx;
}

/**
 * Deriva el conjunto de `node_id` del grupo activo a partir de una lista de
 * `NodeSummaryOut` ya cargada (usa `group_ids`, M1.2 — sin query nueva).
 * `null` sin grupo activo: cada vista lo interpreta como "sin filtrar" en
 * vez de "grupo vacío", para no confundir ambos casos.
 */
export function useGroupNodeIds(summaries: NodeSummaryOut[]): Set<string> | null {
  const { activeGroupId } = useActiveGroup();
  return useMemo(() => {
    if (activeGroupId == null) return null;
    return new Set(
      summaries.filter((s) => s.group_ids.includes(activeGroupId)).map((s) => s.node.node_id),
    );
  }, [summaries, activeGroupId]);
}

/**
 * Alertas dentro/fuera del grupo activo — mismo criterio en toda la app
 * (Alertas, StatusPanel del Centro): una alerta de nodo pertenece al grupo
 * si su nodo es miembro; las de pasarela/sistema nunca se le pueden
 * atribuir a uno, así que siempre cuentan como "dentro". Las CRITICAL de
 * fuera del grupo se devuelven también en `inScope` (nunca se ocultan,
 * v0.7 §2.1) pero marcadas aparte en `outOfGroupCritical` para que cada
 * vista las distinga visualmente sin recalcular el criterio.
 */
export function scopeAlertsToGroup(
  alerts: AlertOut[],
  groupNodeIds: Set<string> | null,
): { inScope: AlertOut[]; outOfGroupCritical: Set<number> } {
  if (groupNodeIds == null) return { inScope: alerts, outOfGroupCritical: new Set() };
  const inScope: AlertOut[] = [];
  const outOfGroupCritical = new Set<number>();
  for (const a of alerts) {
    const belongs = a.subject_type !== "node" || groupNodeIds.has(a.subject_id);
    if (belongs) {
      inScope.push(a);
    } else if (a.severity === "CRITICAL") {
      inScope.push(a);
      outOfGroupCritical.add(a.id);
    }
  }
  return { inScope, outOfGroupCritical };
}

/**
 * Operaciones dentro del grupo activo — mismo patrón que `scopeAlertsToGroup`,
 * usado por Trabajos y por el HUD/StatusBar (fase de cierre de grupos): sin
 * `target_node_id` (no debería ocurrir en la práctica, pero no se le puede
 * atribuir a ningún grupo) se mantiene siempre visible.
 */
export function scopeOperationsToGroup(
  operations: OperationOut[],
  groupNodeIds: Set<string> | null,
): OperationOut[] {
  if (groupNodeIds == null) return operations;
  return operations.filter((o) => o.target_node_id == null || groupNodeIds.has(o.target_node_id));
}

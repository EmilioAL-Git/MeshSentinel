import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchGroups, fetchStartupGroup, type AlertOut, type GroupOut, type NodeSummaryOut, type OperationOut } from "../api/client";
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
  // Ajuste GLOBAL "Grupo al arrancar" (Ajustes → General, guardado en servidor).
  // Se aplica una sola vez al cargar; estado de sesión aparte para que quitar
  // el grupo después no vuelva a caer al de arranque. "last" = recordar el
  // último de este navegador (valor inicial de la sesión).
  const startup = useQuery({ queryKey: ["startup-group"], queryFn: fetchStartupGroup });
  // `undefined` = el operador aún no ha cambiado de grupo en esta sesión.
  const [sessionGroupId, setSessionGroupId] = useState<number | null | undefined>(undefined);
  const startupValue = startup.data?.value;
  const startupGroupId =
    startupValue === "none"
      ? null
      : typeof startupValue === "number" && (groups.data ?? []).some((g) => g.id === startupValue)
        ? startupValue
        : storedGroupId;
  const rawActiveGroupId = urlGroupId ?? (sessionGroupId === undefined ? startupGroupId : sessionGroupId);

  const list = groups.data ?? [];
  // Un grupo que ya no está en la lista (p. ej. el Grupo del usuario tras
  // cerrar sesión o de otra cuenta) no puede seguir filtrando la vista.
  const activeGroupId =
    rawActiveGroupId != null && !groups.isPending && !list.some((g) => g.id === rawActiveGroupId)
      ? null
      : rawActiveGroupId;
  const activeGroup = useMemo(
    () => (activeGroupId != null ? (list.find((g) => g.id === activeGroupId) ?? null) : null),
    [list, activeGroupId],
  );

  const setActiveGroup = useCallback(
    (groupId: number | null) => {
      // El Grupo del usuario NUNCA es predeterminado (ADR 0029): no se recuerda
      // entre sesiones, así que al volver siempre se arranca sin él.
      setStoredGroupId(list.find((g) => g.id === groupId)?.is_personal ? null : groupId);
      setSessionGroupId(groupId);
      setUrlGroupId(groupId);
    },
    [setStoredGroupId, setUrlGroupId, list],
  );
  const clearActiveGroup = useCallback(() => setActiveGroup(null), [setActiveGroup]);

  const value = useMemo<GroupContextValue>(
    () => ({ activeGroupId, activeGroup, groups: list, setActiveGroup, clearActiveGroup }),
    [activeGroupId, activeGroup, list, setActiveGroup, clearActiveGroup],
  );

  // No pintar hasta conocer el grupo de arranque (evita el parpadeo del grupo
  // recordado por el navegador). Con `group` en la URL no hace falta esperar;
  // si el servidor falla (isError) se sigue con lo recordado.
  const ready = urlGroupId != null || (!startup.isPending && !groups.isPending);
  if (!ready) return null;
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
 * Alertas dentro del grupo activo — mismo criterio en toda la app (Alertas,
 * StatusPanel del Centro): una alerta de nodo pertenece al grupo si su nodo
 * es miembro; las de pasarela/sistema nunca se le pueden atribuir a uno, así
 * que siempre cuentan como "dentro". Decisión del usuario 2026-09-29
 * (revierte el principio v0.7 §2.1 "una CRITICAL nunca se oculta"): las
 * CRITICAL de fuera del grupo activo ahora se ocultan igual que cualquier
 * otra — un grupo filtra de verdad, sin excepción de severidad.
 * `outOfGroupCritical` se mantiene en la firma (siempre vacío) para no tocar
 * a cada llamador — las vistas que lo consultaban simplemente dejan de
 * pintar el chip correspondiente.
 */
export function scopeAlertsToGroup(
  alerts: AlertOut[],
  groupNodeIds: Set<string> | null,
): { inScope: AlertOut[]; outOfGroupCritical: Set<number> } {
  if (groupNodeIds == null) return { inScope: alerts, outOfGroupCritical: new Set() };
  const inScope = alerts.filter((a) => a.subject_type !== "node" || groupNodeIds.has(a.subject_id));
  return { inScope, outOfGroupCritical: new Set() };
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

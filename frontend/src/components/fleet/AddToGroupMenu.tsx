import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  addGroupMembersBulk,
  createGroup,
  removeGroupMembersBulk,
  type GroupOut,
  type NodeSummaryOut,
} from "../../api/client";
import { useActiveGroup } from "../../context/GroupContext";
import { t } from "../../tokens";
import { toast } from "../shell/Toast";

/**
 * Gestión masiva de grupos desde Flota (fase 4): añadir/quitar la selección
 * completa de un grupo en una sola llamada — nunca node por node desde el
 * frontend (`addGroupMembersBulk`/`removeGroupMembersBulk`, backend M1.2
 * extendido). El grupo activo, si lo hay, siempre aparece primero en
 * "quitar de" — es el caso de uso más probable (afinar el grupo en el que
 * ya estás trabajando).
 */
export function AddToGroupMenu({
  selectedIds,
  groups,
  allSummaries,
}: {
  selectedIds: string[];
  groups: GroupOut[];
  allSummaries: NodeSummaryOut[];
}) {
  const queryClient = useQueryClient();
  const { activeGroup } = useActiveGroup();
  const [open, setOpen] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, [open]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["groups"] });
    queryClient.invalidateQueries({ queryKey: ["nodes"] });
  };

  const groupName = (id: number) => groups.find((g) => g.id === id)?.name ?? `#${id}`;

  const doAdd = useMutation({
    mutationFn: (groupId: number) => addGroupMembersBulk(groupId, selectedIds),
    onSuccess: (res, groupId) => {
      const name = groupName(groupId);
      toast(
        res.already_member > 0
          ? `${res.added} añadidos, ${res.already_member} ya pertenecían al grupo ${name}`
          : `${res.added} nodos añadidos al grupo ${name}`,
      );
      invalidate();
      setOpen(false);
    },
    onError: (e: Error) => toast(`No se pudo añadir al grupo: ${e.message}`, { kind: "error" }),
  });

  const doRemove = useMutation({
    mutationFn: (groupId: number) => removeGroupMembersBulk(groupId, selectedIds),
    onSuccess: (res, groupId) => {
      const name = groupName(groupId);
      toast(
        res.not_member > 0
          ? `${res.removed} quitados, ${res.not_member} no pertenecían al grupo ${name}`
          : `${res.removed} nodos quitados del grupo ${name}`,
      );
      invalidate();
      setOpen(false);
    },
    onError: (e: Error) => toast(`No se pudo quitar del grupo: ${e.message}`, { kind: "error" }),
  });

  const doCreateAndAdd = useMutation({
    mutationFn: async (name: string) => {
      const group = await createGroup(name);
      const res = await addGroupMembersBulk(group.id, selectedIds);
      return { group, res };
    },
    onSuccess: ({ group, res }) => {
      toast(`${res.added} nodos añadidos al grupo ${group.name} (nuevo)`);
      invalidate();
      setNewGroupName("");
      setOpen(false);
    },
    onError: (e: Error) => toast(`No se pudo crear el grupo: ${e.message}`, { kind: "error" }),
  });

  // Grupos a los que pertenece AL MENOS UNO de los nodos seleccionados —
  // candidatos de "quitar de"; el grupo activo, si lo hay, siempre primero.
  const removableGroups = useMemo(() => {
    const touched = new Set<number>();
    const byId = new Map(allSummaries.map((s) => [s.node.node_id, s]));
    for (const id of selectedIds) {
      for (const gid of byId.get(id)?.group_ids ?? []) touched.add(gid);
    }
    const list = groups.filter((g) => touched.has(g.id));
    if (activeGroup != null) {
      list.sort((a, b) => Number(b.id === activeGroup.id) - Number(a.id === activeGroup.id));
    }
    return list;
  }, [selectedIds, allSummaries, groups, activeGroup]);

  const pending = doAdd.isPending || doRemove.isPending || doCreateAndAdd.isPending;

  return (
    <div ref={rootRef} style={{ position: "relative" }}>
      <button className="btn ghost" onClick={() => setOpen((o) => !o)} disabled={selectedIds.length === 0}>
        📁 Grupo…
      </button>
      {open && (
        <div
          style={{
            position: "absolute",
            bottom: "calc(100% + 4px)",
            left: 0,
            zIndex: 500,
            minWidth: 240,
            maxHeight: 320,
            overflowY: "auto",
            background: t.surface,
            border: `1px solid ${t.border}`,
            borderRadius: 8,
            boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
            padding: "0.5rem",
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          <div className="microlabel">Añadir a grupo</div>
          {groups.length === 0 && (
            <span style={{ color: t.textFaint, fontSize: 12 }}>Sin grupos todavía.</span>
          )}
          {groups.map((g) => (
            <button
              key={g.id}
              className="btn ghost"
              disabled={pending}
              onClick={() => doAdd.mutate(g.id)}
              style={{ justifyContent: "space-between", textAlign: "left" }}
            >
              <span>{g.name}</span>
              <span style={{ color: t.textFaint, fontSize: 11 }}>{g.member_count}</span>
            </button>
          ))}
          <div style={{ display: "flex", gap: 4, marginTop: 2 }}>
            <input
              className="input"
              style={{ flex: 1, minWidth: 0 }}
              placeholder="Crear grupo nuevo…"
              value={newGroupName}
              onChange={(e) => setNewGroupName(e.target.value)}
            />
            <button
              className="btn ghost"
              disabled={!newGroupName.trim() || pending}
              onClick={() => doCreateAndAdd.mutate(newGroupName.trim())}
            >
              Crear
            </button>
          </div>

          {removableGroups.length > 0 && (
            <>
              <div className="microlabel" style={{ marginTop: 8 }}>Quitar de grupo</div>
              {removableGroups.map((g) => (
                <button
                  key={g.id}
                  className="btn ghost"
                  disabled={pending}
                  onClick={() => doRemove.mutate(g.id)}
                  style={{ textAlign: "left", color: g.id === activeGroup?.id ? t.warn : undefined }}
                >
                  Quitar de {g.name}
                  {g.id === activeGroup?.id ? " (activo)" : ""}
                </button>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

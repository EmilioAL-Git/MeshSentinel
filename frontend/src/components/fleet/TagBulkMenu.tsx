import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  addTagBulk,
  createTag,
  fetchTags,
  removeTagBulk,
  type NodeSummaryOut,
} from "../../api/client";
import { t } from "../../tokens";
import { toast } from "../shell/Toast";

/**
 * Etiquetado masivo desde Flota: añade o quita UNA etiqueta a toda la
 * selección en una sola llamada (`addTagBulk`/`removeTagBulk`), sin tocar el
 * resto de etiquetas de cada nodo. Mismo patrón que AddToGroupMenu.
 */
export function TagBulkMenu({
  selectedIds,
  allSummaries,
}: {
  selectedIds: string[];
  allSummaries: NodeSummaryOut[];
}) {
  const queryClient = useQueryClient();
  const tags = useQuery({ queryKey: ["tags"], queryFn: fetchTags });
  const [open, setOpen] = useState(false);
  const [newTagName, setNewTagName] = useState("");
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
    queryClient.invalidateQueries({ queryKey: ["tags"] });
    queryClient.invalidateQueries({ queryKey: ["nodes"] });
  };

  const tagName = (id: number) => tags.data?.find((x) => x.id === id)?.name ?? `#${id}`;

  const doAdd = useMutation({
    mutationFn: (tagId: number) => addTagBulk(tagId, selectedIds),
    onSuccess: (res, tagId) => {
      const name = tagName(tagId);
      toast(
        res.already_member > 0
          ? `${res.added} etiquetados, ${res.already_member} ya tenían la etiqueta ${name}`
          : `${res.added} nodos etiquetados con ${name}`,
      );
      invalidate();
      setOpen(false);
    },
    onError: (e: Error) => toast(`No se pudo añadir la etiqueta: ${e.message}`, { kind: "error" }),
  });

  const doRemove = useMutation({
    mutationFn: (tagId: number) => removeTagBulk(tagId, selectedIds),
    onSuccess: (res, tagId) => {
      const name = tagName(tagId);
      toast(
        res.not_member > 0
          ? `${res.removed} sin la etiqueta ${name}, ${res.not_member} no la tenían`
          : `Etiqueta ${name} quitada de ${res.removed} nodos`,
      );
      invalidate();
      setOpen(false);
    },
    onError: (e: Error) => toast(`No se pudo quitar la etiqueta: ${e.message}`, { kind: "error" }),
  });

  const doCreateAndAdd = useMutation({
    mutationFn: async (name: string) => {
      const tag = await createTag(name);
      const res = await addTagBulk(tag.id, selectedIds);
      return { tag, res };
    },
    onSuccess: ({ tag, res }) => {
      toast(`${res.added} nodos etiquetados con ${tag.name} (nueva)`);
      invalidate();
      setNewTagName("");
      setOpen(false);
    },
    onError: (e: Error) => toast(`No se pudo crear la etiqueta: ${e.message}`, { kind: "error" }),
  });

  // Etiquetas que lleva AL MENOS UNO de los nodos seleccionados: candidatas
  // de "quitar".
  const removableTags = useMemo(() => {
    const touched = new Set<number>();
    const byId = new Map(allSummaries.map((s) => [s.node.node_id, s]));
    for (const id of selectedIds) {
      for (const tag of byId.get(id)?.tags ?? []) touched.add(tag.id);
    }
    return (tags.data ?? []).filter((x) => touched.has(x.id));
  }, [selectedIds, allSummaries, tags.data]);

  const pending = doAdd.isPending || doRemove.isPending || doCreateAndAdd.isPending;

  return (
    <div ref={rootRef} style={{ position: "relative" }}>
      <button className="btn ghost" onClick={() => setOpen((o) => !o)} disabled={selectedIds.length === 0}>
        🏷 Etiqueta…
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
          <div className="microlabel">Añadir etiqueta</div>
          {(tags.data ?? []).length === 0 && (
            <span style={{ color: t.textFaint, fontSize: 12 }}>Sin etiquetas todavía.</span>
          )}
          {(tags.data ?? []).map((tag) => (
            <button
              key={tag.id}
              className="btn ghost"
              disabled={pending}
              onClick={() => doAdd.mutate(tag.id)}
              style={{ textAlign: "left" }}
            >
              {tag.name}
            </button>
          ))}
          <div style={{ display: "flex", gap: 4, marginTop: 2 }}>
            <input
              className="input"
              style={{ flex: 1, minWidth: 0 }}
              placeholder="Crear etiqueta nueva…"
              value={newTagName}
              onChange={(e) => setNewTagName(e.target.value)}
            />
            <button
              className="btn ghost"
              disabled={!newTagName.trim() || pending}
              onClick={() => doCreateAndAdd.mutate(newTagName.trim())}
            >
              Crear
            </button>
          </div>

          {removableTags.length > 0 && (
            <>
              <div className="microlabel" style={{ marginTop: 8 }}>Quitar etiqueta</div>
              {removableTags.map((tag) => (
                <button
                  key={tag.id}
                  className="btn ghost"
                  disabled={pending}
                  onClick={() => doRemove.mutate(tag.id)}
                  style={{ textAlign: "left" }}
                >
                  Quitar {tag.name}
                </button>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

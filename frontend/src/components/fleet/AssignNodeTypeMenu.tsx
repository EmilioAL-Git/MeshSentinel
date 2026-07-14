import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { setNodeTypeOverrideBulk } from "../../api/client";
import { t } from "../../tokens";
import { toast } from "../shell/Toast";
import { NODE_TYPE_OVERRIDE_OPTIONS } from "./classify";

/**
 * Clasificación manual masiva desde la barra de selección de Flota — mismo
 * endpoint bulk que la gestión de grupos (`setNodeTypeOverrideBulk`, un solo
 * viaje sin importar el tamaño de la selección). Mismas opciones que el
 * Inspector (`NODE_TYPE_OVERRIDE_OPTIONS`): "Automático" limpia el override
 * y devuelve los nodos a la clasificación derivada del role de firmware.
 */
export function AssignNodeTypeMenu({ selectedIds }: { selectedIds: string[] }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, [open]);

  const doAssign = useMutation({
    mutationFn: (nodeType: string | null) => setNodeTypeOverrideBulk(selectedIds, nodeType),
    onSuccess: (res, nodeType) => {
      const label = NODE_TYPE_OVERRIDE_OPTIONS.find((o) => o.id === nodeType)?.label ?? nodeType;
      toast(`${res.updated} nodos reclasificados como ${label}`);
      queryClient.invalidateQueries({ queryKey: ["nodes"] });
      setOpen(false);
    },
    onError: (e: Error) => toast(`No se pudo reclasificar: ${e.message}`, { kind: "error" }),
  });

  return (
    <div ref={rootRef} style={{ position: "relative" }}>
      <button className="btn ghost" onClick={() => setOpen((o) => !o)} disabled={selectedIds.length === 0}>
        🏷 Tipo…
      </button>
      {open && (
        <div
          style={{
            position: "absolute",
            bottom: "calc(100% + 4px)",
            left: 0,
            zIndex: 500,
            minWidth: 200,
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
          <div className="microlabel">Asignar tipo de nodo</div>
          {NODE_TYPE_OVERRIDE_OPTIONS.map((opt) => (
            <button
              key={opt.id ?? "auto"}
              className="btn ghost"
              disabled={doAssign.isPending}
              onClick={() => doAssign.mutate(opt.id)}
              style={{ textAlign: "left" }}
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { deleteNode, deleteNodesBulk } from "../../api/client";
import { Modal } from "../shell/Modal";
import { t } from "../../tokens";

/**
 * Confirmación de borrado real de nodo(s) — irreversible, se lleva por
 * delante el historial propio del nodo (posiciones/telemetría/vecinos/tags/
 * grupos/enlaces con pasarela). Distinto de is_ignored (M1.2, reversible).
 * Botón armado en 2 pasos (mismo patrón que GatewaysView), sin teclear nada
 * — pedido explícito del usuario tras probar la versión con confirmación
 * por texto.
 */
export function DeleteNodeModal({
  nodeIds,
  nodeLabel,
  onClose,
  onDeleted,
}: {
  nodeIds: string[];
  /** Solo relevante con un único nodo: "NOMBRE (!id)". */
  nodeLabel?: string;
  onClose: () => void;
  onDeleted: (deletedIds: string[]) => void;
}) {
  const [armed, setArmed] = useState(false);
  const single = nodeIds.length === 1;

  const doDelete = useMutation({
    mutationFn: async () => {
      if (single) await deleteNode(nodeIds[0]);
      else await deleteNodesBulk(nodeIds);
    },
    onSuccess: () => onDeleted(nodeIds),
  });

  return (
    <Modal title={single ? "Borrar nodo" : `Borrar ${nodeIds.length} nodos`} onClose={onClose}>
      <p style={{ marginTop: 0, fontSize: 12.5 }}>
        {single ? (
          <>
            Vas a borrar <strong>{nodeLabel ?? nodeIds[0]}</strong> del sistema.
          </>
        ) : (
          <>
            Vas a borrar <strong>{nodeIds.length} nodos</strong> del sistema.
          </>
        )}
      </p>
      <p style={{ color: t.textDim, fontSize: 12 }}>
        Se elimina la información del nodo y todo su historial propio (posiciones, telemetría,
        vecinos, etiquetas, grupos, enlaces con pasarelas). Es <strong>irreversible</strong>. No es
        como "ignorar", que solo lo oculta.
        <br />
        Los registros de Actividad/Alertas/Operaciones que lo incluyen no se borran.
      </p>
      {armed ? (
        <button
          className="btn danger"
          disabled={doDelete.isPending}
          onClick={() => doDelete.mutate()}
        >
          ¿Seguro? Confirmar borrado
        </button>
      ) : (
        <button className="btn danger" onClick={() => setArmed(true)}>
          Borrar
        </button>
      )}
      {doDelete.isError && <p style={{ color: t.crit, fontSize: 12 }}>{String(doDelete.error)}</p>}
    </Modal>
  );
}

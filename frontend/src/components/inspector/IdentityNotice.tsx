import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { mergeIdentity } from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import { useUrlString } from "../../hooks/useUrlState";
import { useIdentityReport } from "../../hooks/useIdentity";
import { Modal } from "../shell/Modal";
import { toast } from "../shell/Toast";
import { chipStyle, t } from "../../tokens";

/** Avisos de identidad/clave del nodo (ADR 0034): cambio de identidad 2.8
 * (con fusión manual del historial, destructiva y siempre confirmada) y
 * claves débiles/duplicadas. No renderiza nada si el nodo está limpio. */
export function IdentityNotice({ nodeId }: { nodeId: string }) {
  const [, setSelected] = useUrlString("node", null, { replace: false });
  const onOpenNode = (id: string) => setSelected(id);
  const report = useIdentityReport();
  const { canOperate } = useAuth();
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState("");

  const asOld = report?.changes.find((c) => c.predecessor_id === nodeId);
  const asNew = report?.changes.find((c) => c.successor_id === nodeId);
  const dup = report?.duplicate_keys.find((g) => g.node_ids.includes(nodeId));
  const weak = report?.weak_keys.find((w) => w.node_id === nodeId);
  const change = asOld ?? asNew;

  const merge = useMutation({
    mutationFn: () => mergeIdentity(change!.predecessor_id, change!.successor_id),
    onSuccess: (res) => {
      const total = Object.values(res.moved).reduce((a, b) => a + b, 0);
      toast(`Historial fusionado (${total} registros movidos)`);
      setConfirming(false);
      queryClient.invalidateQueries();
      onOpenNode?.(change!.successor_id);
    },
    onError: (e: Error) => toast(`No se pudo fusionar: ${e.message}`, { kind: "error" }),
  });

  if (!change && !dup && !weak) return null;
  const other = change ? (asOld ? change.successor_id : change.predecessor_id) : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 10 }}>
      {change && (
        <div style={{ ...chipStyle(t.warn), fontSize: 11, lineHeight: 1.5, display: "block", whiteSpace: "normal" }}>
          ⇄ {asOld ? "Identidad antigua" : "Nueva identidad 2.8"}: {asOld ? "sustituida por" : "sustituye a"}{" "}
          <a style={{ cursor: "pointer", textDecoration: "underline" }} onClick={() => onOpenNode?.(other!)}>
            {other}
          </a>{" "}
          <span style={{ color: t.textDim }}>
            (misma clave · {change.basis === "same_key" ? "clave idéntica" : "número derivado de la clave"}
            {change.predecessor_quiet === false ? " · el antiguo sigue oyéndose" : ""})
          </span>
          {canOperate && (
            <button className="btn" style={{ marginLeft: 8 }} onClick={() => setConfirming(true)}>
              Fusionar historial…
            </button>
          )}
        </div>
      )}
      {dup && (
        <div style={{ ...chipStyle(t.warn), fontSize: 11, display: "block", whiteSpace: "normal" }}>
          ⚠ Clave duplicada con {dup.node_ids.filter((i) => i !== nodeId).join(", ")} — clonado o generación defectuosa
        </div>
      )}
      {weak && (
        <div style={{ ...chipStyle(t.crit), fontSize: 11, display: "block", whiteSpace: "normal" }}>
          ⚠ Clave de baja entropía: {weak.reason}
        </div>
      )}
      {confirming && change && (
        <Modal title="Fusionar historial de identidad" onClose={() => setConfirming(false)}>
          <p style={{ margin: "0 0 10px", fontSize: 13, lineHeight: 1.5 }}>
            Se moverán telemetría, posiciones, vecinos, mensajes, etiquetas, grupos, favoritos y enlaces de{" "}
            <strong>{change.predecessor_id}</strong> a <strong>{change.successor_id}</strong>, y el nodo antiguo se
            borrará. <strong>No se puede deshacer.</strong> Escribe el id del nodo antiguo para confirmar.
          </p>
          <input
            className="input"
            autoFocus
            placeholder={change.predecessor_id}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            style={{ width: "100%", marginBottom: 10 }}
          />
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <button className="btn ghost" onClick={() => setConfirming(false)}>
              Cancelar
            </button>
            <button
              className="btn danger"
              disabled={typed !== change.predecessor_id || merge.isPending}
              onClick={() => merge.mutate()}
            >
              Fusionar
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

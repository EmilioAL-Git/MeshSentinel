import { useState } from "react";
import { Modal } from "../shell/Modal";
import { t } from "../../tokens";

/**
 * Confirmación para ignorar un nodo (M1.2, local y reversible). Botón armado
 * en 2 pasos, mismo patrón que DeleteNodeModal. Solo se pide al ignorar:
 * dejar de ignorar no necesita confirmación.
 */
export function IgnoreNodeModal({
  nodeLabel,
  onClose,
  onConfirm,
}: {
  /** "NOMBRE (!id)". */
  nodeLabel: string;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const [armed, setArmed] = useState(false);

  return (
    <Modal title="Ignorar nodo" onClose={onClose}>
      <p style={{ marginTop: 0, fontSize: 12.5 }}>
        Vas a ignorar <strong>{nodeLabel}</strong>.
      </p>
      <p style={{ color: t.textDim, fontSize: 12 }}>
        Deja de aparecer en la flota, el mapa y los agregados del Dashboard, y sus alertas se
        resuelven solas. Su telemetría se sigue guardando y puedes dejar de ignorarlo cuando
        quieras.
      </p>
      {armed ? (
        <button className="btn danger" onClick={onConfirm}>
          ¿Seguro? Confirmar
        </button>
      ) : (
        <button className="btn danger" onClick={() => setArmed(true)}>
          Ignorar
        </button>
      )}
    </Modal>
  );
}

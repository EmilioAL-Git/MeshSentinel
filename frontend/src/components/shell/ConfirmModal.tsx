import { t } from "../../tokens";
import { Modal } from "./Modal";

/** Cuadro de confirmación genérico (mismo cascarón que Modal) para
 * acciones que conviene detener con una pregunta explícita, sin recurrir
 * a window.confirm — pedido explícito del usuario, quería el estilo de
 * la app. */
export function ConfirmModal({
  title,
  message,
  confirmLabel = "Confirmar",
  danger,
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal title={title} onClose={onCancel}>
      <p style={{ margin: "0 0 1rem", color: t.text, fontSize: 13, lineHeight: 1.5 }}>{message}</p>
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button className="btn ghost" onClick={onCancel}>
          Cancelar
        </button>
        <button
          className={`btn ${danger ? "danger" : "primary"}`}
          onClick={() => {
            onConfirm();
          }}
        >
          {confirmLabel}
        </button>
      </div>
    </Modal>
  );
}

import { t } from "../../tokens";

/**
 * Sugerencia bajo el botón de enviar tras encolar un comando que necesita SAVE
 * (cambia la configuración en RAM y no sobrevive a un reinicio sin guardar).
 * No envía nada sola: hace falta pulsar «Enviar SAVE ahora».
 */
export function NexusSaveSuggestion({
  command, pending, onSend, onDismiss,
}: {
  command: string;
  pending: boolean;
  onSend: () => void;
  onDismiss: () => void;
}) {
  return (
    <div
      style={{
        marginTop: 8, padding: "0.45rem 0.6rem", border: `1px solid ${t.warn}`, borderRadius: 6,
        display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", fontSize: 11.5,
      }}
    >
      <span style={{ color: t.warn }}>
        💾 <span className="mono">{command}</span> necesita SAVE para sobrevivir a un reinicio. ¿Enviar SAVE ahora?
      </span>
      <button className="btn primary" disabled={pending} onClick={onSend}>Enviar SAVE ahora</button>
      <button className="btn ghost" disabled={pending} onClick={onDismiss}>Ahora no</button>
    </div>
  );
}

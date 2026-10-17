import { t } from "../../tokens";

/** `SETCONFIG LOC …` solo se mantiene si el GPS del nodo no lo pisa. */
export function isManualLoc(command: string, args: string[]): boolean {
  return command.trim().toUpperCase() === "SETCONFIG" && (args[0] ?? "").toUpperCase() === "LOC";
}

/**
 * Sugerencia dentro de la previsualización de unas coordenadas manuales:
 * mandar antes `SETCONFIG GPS OFF`. No envía nada sola.
 */
export function NexusGpsOffSuggestion({
  command, args, pending, onSend,
}: {
  command: string;
  args: string[];
  pending: boolean;
  onSend: () => void;
}) {
  if (!isManualLoc(command, args)) return null;
  return (
    <div
      style={{
        marginTop: 8, padding: "0.45rem 0.6rem", border: `1px solid ${t.warn}`, borderRadius: 6,
        display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", fontSize: 11.5,
      }}
    >
      <span style={{ color: t.warn }}>
        📡 Si el GPS sigue activo puede pisar las coordenadas. Se recomienda enviar antes{" "}
        <span className="mono">SETCONFIG GPS OFF</span>.
      </span>
      <button className="btn" disabled={pending} onClick={onSend}>Enviar GPS OFF primero</button>
    </div>
  );
}

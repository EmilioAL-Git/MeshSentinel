import { useEffect, useState } from "react";
import { t } from "../../tokens";

/**
 * Indicador permanente de Focus (v0.7 §7.2): mientras hay un objetivo
 * enfocado, este chip vive en la cabecera con el tiempo transcurrido —
 * recuerda que el contexto está sesgado — y el ✕ es la salida explícita.
 * Sin Focus activo no se renderiza nada: cero ambigüedad.
 */

export interface FocusState {
  id: string;
  since: number; // epoch ms
}

export function FocusChip({
  focus,
  label,
  onOpen,
  onExit,
}: {
  focus: FocusState;
  label: string;
  onOpen: () => void;
  onExit: () => void;
}) {
  // Rerender por minuto para el contador de tiempo
  const [, tick] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => tick((x) => x + 1), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const minutes = Math.floor((Date.now() - focus.since) / 60_000);
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "0.4rem",
        background: t.accentTint,
        border: `1px solid ${t.accent}`,
        borderRadius: 12,
        padding: "0.1rem 0.3rem 0.1rem 0.6rem",
        fontFamily: t.fontMono,
        fontSize: 11.5,
        color: t.accent,
        whiteSpace: "nowrap",
      }}
      title={`Focus activo en ${label} — la actividad, los trabajos y el mapa priorizan este nodo (nada se oculta)`}
    >
      <span style={{ cursor: "pointer" }} onClick={onOpen}>
        ◎ {label}
        {minutes > 0 && <span style={{ opacity: 0.75 }}> · {minutes}m</span>}
      </span>
      <button
        onClick={onExit}
        title="Salir de Focus"
        style={{
          background: "none",
          border: "none",
          color: t.accent,
          cursor: "pointer",
          fontSize: 12,
          padding: "0 0.25rem",
          lineHeight: 1,
        }}
      >
        ✕
      </button>
    </span>
  );
}

import { useEffect, useState } from "react";
import { t } from "../../tokens";

/**
 * Toasts de MeshSentinel (v0.7 §14.5): confirmaciones abajo-derecha, 4 s,
 * los errores persisten hasta cerrarse. Emisor a nivel de módulo para poder
 * lanzar un toast desde cualquier componente o mutación sin contexto React:
 *   toast("Operación añadida a la cola");
 *   toast("No se pudo encolar", { kind: "error" });
 */

export interface ToastMsg {
  id: number;
  text: string;
  kind: "ok" | "error";
}

type Listener = (msg: ToastMsg) => void;
let listener: Listener | null = null;
let nextId = 1;

export function toast(text: string, opts: { kind?: "ok" | "error" } = {}): void {
  listener?.({ id: nextId++, text, kind: opts.kind ?? "ok" });
}

const TOAST_MS = 4_000;

export function ToastHost() {
  const [toasts, setToasts] = useState<ToastMsg[]>([]);

  useEffect(() => {
    listener = (msg) => {
      setToasts((prev) => [...prev.slice(-3), msg]);
      if (msg.kind === "ok") {
        window.setTimeout(() => setToasts((prev) => prev.filter((m) => m.id !== msg.id)), TOAST_MS);
      }
    };
    return () => {
      listener = null;
    };
  }, []);

  if (toasts.length === 0) return null;
  return (
    <div
      style={{
        position: "fixed",
        right: 16,
        bottom: "calc(var(--statusbar-height) + 12px)",
        zIndex: 990,
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      {toasts.map((m) => (
        <div
          key={m.id}
          onClick={() => setToasts((prev) => prev.filter((x) => x.id !== m.id))}
          style={{
            background: t.surface,
            border: `1px solid ${m.kind === "error" ? t.crit : t.border}`,
            borderLeft: `3px solid ${m.kind === "error" ? t.crit : t.ok}`,
            color: m.kind === "error" ? t.crit : t.text,
            borderRadius: 6,
            padding: "0.5rem 0.9rem",
            fontSize: 12.5,
            boxShadow: "0 6px 20px rgba(0, 0, 0, 0.45)",
            cursor: "pointer",
            maxWidth: 380,
          }}
          title="Clic para cerrar"
        >
          {m.text}
        </div>
      ))}
    </div>
  );
}

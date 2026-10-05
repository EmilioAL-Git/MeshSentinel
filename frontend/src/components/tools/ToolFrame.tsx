import type { ReactNode } from "react";
import { t } from "../../tokens";

/** Marco común de las herramientas: migas «← Herramientas / <nombre>» + contenido. */
export function ToolFrame({
  title,
  onBack,
  children,
}: {
  title: string;
  onBack: () => void;
  children: ReactNode;
}) {
  return (
    <div className="ws">
      <div className="toolbar" style={{ flexShrink: 0, gap: 8 }}>
        <button className="btn ghost" onClick={onBack}>
          ← Herramientas
        </button>
        <span style={{ color: t.textFaint }}>/</span>
        <span style={{ fontWeight: 650 }}>{title}</span>
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>{children}</div>
    </div>
  );
}

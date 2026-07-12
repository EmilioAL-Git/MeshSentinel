import { useActiveGroup } from "../../context/GroupContext";
import { t } from "../../tokens";

/**
 * Indicador de alcance por grupo activo (fase "Grupo como contexto global"):
 * reutilizado por Trabajos, Alertas y Registro — misma banda, mismo
 * vocabulario ("mostrando X de Y"), mismo acceso de un clic a "Toda la red"
 * (además del que ya vive siempre en el HUD). No se renderiza nada sin
 * grupo activo — cero ruido en el modo global.
 */
export function GroupScopeBanner({ shown, total, label }: { shown: number; total: number; label: string }) {
  const { activeGroup, clearActiveGroup } = useActiveGroup();
  if (activeGroup == null) return null;
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.6rem",
        padding: "0.35rem 0.75rem",
        background: t.accentTint,
        borderBottom: `1px solid ${t.accent}`,
        fontSize: 11.5,
        flexShrink: 0,
      }}
    >
      <span style={{ color: t.accent, fontWeight: 600 }}>📁 {activeGroup.name}</span>
      <span className="mono" style={{ color: t.textDim, fontVariantNumeric: "tabular-nums" }}>
        mostrando {shown} de {total} {label}
      </span>
      <span style={{ marginLeft: "auto" }} />
      <button className="btn ghost" style={{ fontSize: 11 }} onClick={clearActiveGroup} title="Volver al modo global">
        Toda la red
      </button>
    </div>
  );
}

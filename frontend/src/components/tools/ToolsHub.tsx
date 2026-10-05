import type { View } from "../../view";
import { t } from "../../tokens";

interface Tool {
  id: View | null;
  icon: string;
  title: string;
  text: string;
}

const TOOLS: Tool[] = [
  {
    id: "traces",
    icon: "⌁",
    title: "Historial de trazas",
    text: "Todos los traceroutes guardados, activos y oídos en la malla. Filtra, repite o ábrelos en 3D. Rescata también los antiguos del Registro.",
  },
  {
    id: "map3d",
    icon: "◈",
    title: "Mapa 3D",
    text: "Reproduce una traza en relieve 3D: pilares en los nodos, arcos por SNR y un pulso que recorre la ida y la vuelta.",
  },
  {
    id: "config",
    icon: "⚙",
    title: "Administración remota",
    text: "Lee y cambia la configuración de un nodo por radio (config, módulos, propietario, posición) con verificación.",
  },
];

const SOON: Omit<Tool, "id">[] = [
  { icon: "⇄", title: "Comparador de trazas", text: "Dos trazas al mismo destino lado a lado: qué ruta o enlace cambió." },
  { icon: "⛰", title: "Perfil de elevación", text: "Terreno entre dos nodos y línea de visión: ¿hay una montaña de por medio?" },
];

export function ToolsHub({ onGoTo }: { onGoTo: (v: View) => void }) {
  return (
    <div className="ws">
      <div className="panel-head">
        <span className="panel-title">Herramientas</span>
      </div>
      <div className="ws-scroll" style={{ padding: "0.9rem" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
            gap: 12,
          }}
        >
          {TOOLS.map((tool) => (
            <button
              key={tool.title}
              className="panel tool-card"
              onClick={() => tool.id && onGoTo(tool.id)}
              style={{ textAlign: "left", cursor: "pointer", padding: 14, gap: 6, color: "inherit", font: "inherit" }}
            >
              <span style={{ fontSize: 22, color: t.accent }} aria-hidden>
                {tool.icon}
              </span>
              <span style={{ fontWeight: 650, fontSize: 14 }}>{tool.title}</span>
              <span style={{ color: t.textDim, fontSize: 12.5, lineHeight: 1.45 }}>{tool.text}</span>
            </button>
          ))}
          {SOON.map((tool) => (
            <div
              key={tool.title}
              className="panel"
              style={{ padding: 14, gap: 6, opacity: 0.5, borderStyle: "dashed" }}
              title="Próximamente"
            >
              <span style={{ fontSize: 22 }} aria-hidden>
                {tool.icon}
              </span>
              <span style={{ fontWeight: 650, fontSize: 14 }}>
                {tool.title} <span className="chip">próximamente</span>
              </span>
              <span style={{ color: t.textDim, fontSize: 12.5, lineHeight: 1.45 }}>{tool.text}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

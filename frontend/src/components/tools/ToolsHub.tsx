import type { View } from "../../view";
import { useUrlString } from "../../hooks/useUrlState";
import { t } from "../../tokens";

interface Tool {
  id: View | null;
  icon: string;
  title: string;
  text: string;
  params?: Record<string, string>;
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
    text: "Mapa en relieve 3D con satélite y todos los nodos. Busca un nodo y verás sus traceroutes: pilares, arcos por SNR y un pulso que recorre la ida y la vuelta.",
  },
  {
    id: "map3d",
    icon: "⛰",
    title: "Perfil de elevación",
    text: "Terreno entre dos nodos y línea de visión con curvatura terrestre y zona de Fresnel: ¿hay una montaña de por medio?",
    params: { "m3d.tab": "profile" },
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
];

export function ToolsHub({ onGoTo }: { onGoTo: (v: View) => void }) {
  const [, setM3dTab] = useUrlString("m3d.tab");
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
              onClick={() => {
                if (!tool.id) return;
                // Cada tarjeta del Mapa 3D abre su herramienta (la URL conserva la query)
                if (tool.id === "map3d") setM3dTab(tool.params?.["m3d.tab"] ?? null);
                onGoTo(tool.id);
              }}
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

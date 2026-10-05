/**
 * Traza de demostración para el mapa 3D: ocho nodos; la ida pasa por 4 intermedios y la
 * vuelta vuelve por otro camino (3 intermedios). NO se guarda en la base de datos (los nodos reales
 * de esa zona casi no tienen GPS y no queremos inventar posiciones de nodos reales):
 * vive solo aquí, con ids ficticios `!fa0000NN` y coordenadas APROXIMADAS.
 */
import type { TraceOut } from "../../api/client";
import type { LngLat } from "./traceGeometry";

export const DEMO_TRACE_ID = -1;

const NODES: { id: string; name: string; pos: LngLat }[] = [
  { id: "!fa000001", name: "emyC tracker", pos: [-1.8694, 38.9956] },
  { id: "!fa000002", name: "AB - Parque Abelardo", pos: [-1.8561, 38.9943] },
  { id: "!fa000003", name: "AB - Chinchilla Tower", pos: [-1.7203, 38.9186] },
  { id: "!fa000004", name: "AB - Molatower", pos: [-1.4057, 38.9906] },
  { id: "!fa000005", name: "AB - La Coronilla", pos: [-2.3626, 38.6302] },
  { id: "!fa000006", name: "MU - Columbares", pos: [-1.0, 38.15] },
  // Solo en la vuelta
  { id: "!fa000007", name: "AB - Hellín", pos: [-1.7003, 38.5106] },
  { id: "!fa000008", name: "AB - Ejidos Feria", pos: [-1.8365, 38.9895] },
];

export const DEMO_NODE_INFO = new Map(NODES.map((n) => [n.id, { name: n.name, pos: n.pos }]));

export function demoTrace(): TraceOut {
  // Ida: emyC → Abelardo → Chinchilla → Molatower → Coronilla → Columbares
  const [emy, abelardo, chinchilla, molatower, coronilla, columbares, hellin, ejidos] = NODES.map((n) => n.id);
  return {
    id: DEMO_TRACE_ID,
    gateway_id: "demo",
    origin_id: emy,
    target_id: columbares,
    source: "active",
    kind: "reply",
    reached: true,
    route: [abelardo, chinchilla, molatower, coronilla],
    // Vuelta por OTRO camino: Columbares → Hellín → Chinchilla → Ejidos Feria → emyC
    route_back: [hellin, chinchilla, ejidos],
    snr_towards: [9.5, 6.0, 2.5, -1.0, -5.5],
    snr_back: [7.5, 3.5, -2.0, -6.5],
    operation_id: null,
    received_at: new Date().toISOString(),
  };
}

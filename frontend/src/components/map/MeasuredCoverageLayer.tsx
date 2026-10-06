import { useQuery } from "@tanstack/react-query";
import { Circle, Tooltip } from "react-leaflet";
import { fetchCoverage } from "../../api/client";
import { snrColor } from "./geometry";

/**
 * Capa "Cobertura medida" (ADR 0035): celdas de ~110 m con el SNR medio de
 * las posiciones que una pasarela oyó A 0 SALTOS. A diferencia de la capa
 * "Cobertura" (envolvente convexa, aproximada), esto es señal REAL medida —
 * pero solo donde hubo un nodo con GPS emitiendo: una zona sin celda no
 * significa "sin cobertura", significa "sin medición".
 */
export function MeasuredCoverageLayer() {
  const { data } = useQuery({ queryKey: ["coverage"], queryFn: () => fetchCoverage(), refetchInterval: 120_000 });
  return (
    <>
      {(data ?? []).map((c) => (
        <Circle
          key={`${c.latitude},${c.longitude}`}
          center={[c.latitude, c.longitude]}
          radius={60}
          pathOptions={{ stroke: false, fillColor: snrColor(c.avg_snr), fillOpacity: 0.55 }}
          interactive
        >
          <Tooltip sticky>
            SNR medio {c.avg_snr} dB (máx {c.max_snr}) · {c.receptions} recepciones · {c.nodes}{" "}
            {c.nodes === 1 ? "nodo" : "nodos"}
          </Tooltip>
        </Circle>
      ))}
    </>
  );
}

import { useQuery } from "@tanstack/react-query";
import { Polyline } from "react-leaflet";
import { fetchTopology, type NodeSummaryOut } from "../../api/client";
import { snrColor } from "./geometry";

/**
 * Capa "Enlaces (malla real)" (topología, motor-de-reglas-y-topologia.md §2):
 * a diferencia de `LinksLayer` (nodo↔pasarela, la única relación que el
 * sistema captaba antes), esta pinta enlaces nodo↔nodo REALES oídos por
 * NEIGHBORINFO_APP — la topología de retransmisión de la malla, no solo
 * quién oye a quién desde la pasarela. Requiere que el firmware tenga el
 * módulo NeighborInfo activado; si ningún nodo lo tiene, la capa
 * simplemente no pinta nada (nunca degrada `LinksLayer`).
 */
export function NeighborsLayer({ summaries }: { summaries: NodeSummaryOut[] }) {
  const { data: links } = useQuery({
    queryKey: ["topology"],
    queryFn: () => fetchTopology(),
    refetchInterval: 20_000,
  });

  const positionOf = new Map<string, [number, number]>();
  for (const s of summaries) {
    if (s.last_position) positionOf.set(s.node.node_id, [s.last_position.latitude, s.last_position.longitude]);
  }

  // NeighborInfo lo reporta cada nodo por separado: un par que se oye
  // mutuamente llega como dos filas (A→B y B→A). Se dibuja un solo trazo por
  // par no ordenado (nunca duplicado exacto encima de sí mismo), quedándose
  // con el enlace activo/mejor SNR si hay conflicto entre ambos sentidos.
  const byPair = new Map<string, { from: [number, number]; to: [number, number]; active: boolean; snr: number | null }>();
  for (const l of links ?? []) {
    const from = positionOf.get(l.node_id);
    const to = positionOf.get(l.neighbor_id);
    if (!from || !to) continue;
    const pairKey = [l.node_id, l.neighbor_id].sort().join("|");
    const existing = byPair.get(pairKey);
    if (!existing || (l.active && !existing.active) || (l.active === existing.active && (l.snr ?? -Infinity) > (existing.snr ?? -Infinity))) {
      byPair.set(pairKey, { from, to, active: l.active, snr: l.snr });
    }
  }
  const lines = Array.from(byPair.entries()).map(([key, l]) => ({
    key,
    from: l.from,
    to: l.to,
    color: l.active ? snrColor(l.snr) : "var(--text-faint)",
  }));

  return (
    <>
      {lines.map((l) => (
        <Polyline
          key={l.key}
          positions={[l.from, l.to]}
          pathOptions={{ color: l.color, weight: 1.5, opacity: 0.55, dashArray: "1 5" }}
          interactive={false}
        />
      ))}
    </>
  );
}

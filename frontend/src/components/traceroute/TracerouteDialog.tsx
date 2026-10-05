import { Modal } from "../shell/Modal";
import { Signal } from "../fleet/instruments";
import { t } from "../../tokens";
import type { TracerouteOutcome } from "../../opTracker";

/** Datos de un nodo para pintarlo; `null` = id que el sistema no conoce. */
export interface TraceNodeInfo {
  longName: string | null;
  shortName: string | null;
  hwModel: string | null;
}

interface Props {
  outcome: TracerouteOutcome;
  /** Nodo conocido por id (o null). */
  lookup: (nodeId: string) => TraceNodeInfo | null;
  /** Nodo local de la pasarela que lanzó el traceroute (origen real del paquete). */
  originNodeId: string | null;
  originGatewayName: string;
  onOpenNode: (nodeId: string) => void;
  onClose: () => void;
}

type Role = "origin" | "hop" | "dest";

const ERROR_TEXT: Record<string, string> = {
  NO_RESPONSE: "El nodo no contestó a tiempo.",
  NO_ROUTE: "El firmware no encontró ruta hasta el nodo.",
  MAX_RETRANSMIT: "Se agotaron los reintentos sin confirmación.",
  NO_CHANNEL: "El nodo no comparte canal con la pasarela.",
  TIMEOUT: "Tiempo de espera agotado.",
  PKI_UNKNOWN_PUBKEY: "El nodo no conoce la clave pública de la pasarela.",
};

/** Calidad de un enlace LoRa según su SNR (LoRa decodifica hasta ≈ −20 dB). */
function quality(snr: number | null): { label: string; color: string } {
  if (snr == null) return { label: "sin dato", color: t.textFaint };
  if (snr >= 5) return { label: "buena", color: "var(--ok)" };
  if (snr >= 0) return { label: "aceptable", color: "var(--ok)" };
  if (snr >= -7) return { label: "débil", color: "var(--warn)" };
  return { label: "muy débil", color: "var(--crit)" };
}

function NodeCard({
  id, role, hopIndex, info, originLabel, destLabel,
}: { id: string; role: Role; hopIndex?: number; info: TraceNodeInfo | null; originLabel: string; destLabel: string }) {
  const roleLabel = role === "origin" ? originLabel : role === "dest" ? destLabel : `SALTO ${hopIndex}`;
  const accent = role === "origin" ? t.accent : role === "dest" ? "var(--ok)" : t.borderSubtle;
  const name = info?.longName || info?.shortName || null;
  return (
    <div
      className="trace-node"
      style={{ border: `1px solid ${role === "hop" ? t.border : accent}`, borderLeft: `3px solid ${accent}`, background: t.surface2 }}
    >
      <div style={{ fontSize: 10, letterSpacing: "0.08em", color: role === "hop" ? t.textDim : accent, fontWeight: 650 }}>{roleLabel}</div>
      <div style={{ fontWeight: 650, fontSize: 13, overflowWrap: "anywhere" }}>
        {name ?? <span style={{ color: t.textDim }}>nodo no registrado</span>}
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginTop: 2 }}>
        {info?.shortName && <span className="chip">{info.shortName}</span>}
        <span className="mono" style={{ fontSize: 11.5, color: t.textDim }}>{id}</span>
      </div>
      {info?.hwModel && <div style={{ fontSize: 11, color: t.textFaint, marginTop: 2 }}>{info.hwModel}</div>}
    </div>
  );
}

function Link({ snr }: { snr: number | null }) {
  const q = quality(snr);
  return (
    <div className="trace-link" title="SNR del enlace: cuanto más alto, mejor señal">
      <span className="trace-arrow" style={{ color: q.color }}>→</span>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
        <Signal snr={snr} />
        <span className="mono" style={{ fontSize: 12, color: q.color, fontWeight: 650 }}>{snr == null ? "—" : `${snr} dB`}</span>
      </span>
      <span style={{ fontSize: 10.5, color: q.color }}>{q.label}</span>
    </div>
  );
}

function Path({
  title, from, to, via, snrs, lookup, originLabel, destLabel,
}: {
  originLabel: string;
  destLabel: string;
  title: string;
  from: string;
  to: string;
  via: string[];
  snrs: (number | null)[];
  lookup: (id: string) => TraceNodeInfo | null;
}) {
  const chain = [from, ...via, to];
  return (
    <div>
      <div className="panel-title" style={{ marginBottom: 6 }}>{title}</div>
      <div className="trace-path">
        {chain.map((id, i) => (
          <div key={`${id}-${i}`} className="trace-step">
            {i > 0 && <Link snr={snrs[i - 1] ?? null} />}
            <NodeCard
              id={id}
              role={i === 0 ? "origin" : i === chain.length - 1 ? "dest" : "hop"}
              hopIndex={i}
              info={lookup(id)}
              originLabel={originLabel}
              destLabel={destLabel}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

export function TracerouteDialog({ outcome, lookup, originNodeId, originGatewayName, onOpenNode, onClose }: Props) {
  const { result, nodeId } = outcome;
  const destInfo = lookup(nodeId);
  const destName = destInfo?.longName || destInfo?.shortName || nodeId;
  const origin = originNodeId ?? "(nodo local de la pasarela)";

  if (!result.reached) {
    const why = ERROR_TEXT[result.error_reason ?? ""] ?? `No se pudo completar (${result.error_reason ?? "motivo desconocido"}).`;
    return (
      <Modal title={`Traceroute a ${destName}`} onClose={onClose} width="min(520px, 94vw)">
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ color: "var(--warn)", fontWeight: 650 }}>Sin resultado</div>
          <div style={{ fontSize: 13 }}>{why}</div>
          <div style={{ color: t.textDim, fontSize: 12.5 }}>
            {result.waited_seconds ? `Se esperó ${Math.round(result.waited_seconds)} s. ` : ""}
            Puede estar apagado, fuera de alcance, no compartir canal con la pasarela {originGatewayName}, o la malla
            estar saturada. Un traceroute sin respuesta no se reintenta solo (cada intento inunda la malla).
          </div>
          <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
            <button className="btn ghost" onClick={() => { onOpenNode(nodeId); onClose(); }}>Abrir nodo</button>
            <button className="btn" onClick={onClose}>Cerrar</button>
          </div>
        </div>
      </Modal>
    );
  }

  const via = result.route ?? [];
  const back = result.route_back ?? [];
  const totalHops = via.length;
  const summary = totalHops === 0 ? "Alcance directo, sin saltos intermedios" : `${totalHops} salto${totalHops === 1 ? "" : "s"} intermedio${totalHops === 1 ? "" : "s"}`;
  const worst = [...(result.snr_towards ?? []), ...(result.snr_back ?? [])].filter((x): x is number => typeof x === "number");
  const weakest = worst.length ? Math.min(...worst) : null;

  return (
    <Modal title={`Traceroute a ${destName}`} onClose={onClose} width="min(1100px, 96vw)">
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
          <span style={{ color: "var(--ok)", fontWeight: 650 }}>✓ {summary}</span>
          <span style={{ color: t.textDim, fontSize: 12.5 }}>
            vía pasarela {originGatewayName}
            {weakest != null && <> · enlace más débil <b style={{ color: quality(weakest).color }}>{weakest} dB</b> ({quality(weakest).label})</>}
          </span>
        </div>

        <Path originLabel="PASARELA · ORIGEN" destLabel="DESTINO" title="IDA · pasarela → destino" from={origin} to={nodeId} via={via} snrs={result.snr_towards ?? []} lookup={lookup} />
        <Path originLabel="ORIGEN" destLabel="PASARELA · DESTINO" title="VUELTA · destino → pasarela" from={nodeId} to={origin} via={back} snrs={result.snr_back ?? []} lookup={lookup} />

        <div style={{ color: t.textFaint, fontSize: 11.5 }}>
          SNR en dB por enlace (cada flecha es un salto de radio): cuanto más alto, mejor. LoRa llega a decodificar
          hasta ≈ −20 dB; por debajo de −7 dB el enlace es muy frágil. La ida y la vuelta pueden seguir caminos
          distintos.
        </div>

        <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
          <button className="btn ghost" onClick={() => { onOpenNode(nodeId); onClose(); }}>Abrir nodo destino</button>
          <button className="btn" onClick={onClose}>Cerrar</button>
        </div>
      </div>
    </Modal>
  );
}

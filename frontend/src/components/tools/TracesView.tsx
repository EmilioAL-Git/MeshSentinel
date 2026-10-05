import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createOperation,
  fetchTraces,
  importLegacyTraces,
  type GatewayOut,
  type NodeSummaryOut,
  type TraceOut,
} from "../../api/client";
import { toast } from "../shell/Toast";
import { trackOperations } from "../../opTracker";
import { relativeTime } from "../../time";
import { snrColor } from "../map3d/traceGeometry";
import { t } from "../../tokens";

/**
 * Historial de trazas: rescata cualquier traceroute guardado (ADR 0031) para
 * revisarlo, repetirlo o abrirlo en el mapa 3D.
 */

const PERIODS = [
  { id: "24", label: "Últimas 24 h", hours: 24 },
  { id: "168", label: "7 días", hours: 168 },
  { id: "720", label: "30 días", hours: 720 },
  { id: "all", label: "Todo", hours: undefined },
] as const;

function worstSnr(tr: TraceOut): number | null {
  const all = [...tr.snr_towards, ...tr.snr_back].filter((x): x is number => typeof x === "number");
  return all.length ? Math.min(...all) : null;
}

export function TracesView({
  summaries,
  gateways,
  canOperate,
  onOpenNode,
  onView3D,
}: {
  summaries: NodeSummaryOut[];
  gateways: GatewayOut[];
  canOperate: boolean;
  onOpenNode: (id: string) => void;
  onView3D: (traceId: number) => void;
}) {
  const qc = useQueryClient();
  const [period, setPeriod] = useState<(typeof PERIODS)[number]["id"]>("168");
  const [gateway, setGateway] = useState("");
  const [result, setResult] = useState<"" | "ok" | "none">("");
  const [source, setSource] = useState<"" | "active" | "passive">("");
  const [text, setText] = useState("");

  const hours = PERIODS.find((p) => p.id === period)?.hours;
  const list = useQuery({
    queryKey: ["traces", "history", period, gateway, result, source],
    queryFn: () =>
      fetchTraces({
        limit: 500,
        sinceHours: hours,
        gatewayId: gateway || undefined,
        source: source || undefined,
        reached: result === "" ? undefined : result === "ok",
      }),
    refetchInterval: 15_000,
  });

  const names = useMemo(() => {
    const m = new Map<string, string>();
    for (const s of summaries) m.set(s.node.node_id, s.node.long_name || s.node.short_name || s.node.node_id);
    return m;
  }, [summaries]);
  const nameOf = (id: string) => names.get(id) ?? id;

  const rows = useMemo(() => {
    const q = text.trim().toLowerCase();
    return (list.data ?? []).filter(
      (r) =>
        !q ||
        [r.origin_id, r.target_id, nameOf(r.origin_id), nameOf(r.target_id), ...r.route, ...r.route_back]
          .join(" ")
          .toLowerCase()
          .includes(q),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list.data, text, names]);

  const repeat = useMutation({
    mutationFn: (nodeId: string) => createOperation({ node_id: nodeId, operation_type: "traceroute.run" }),
    onSuccess: (op) => {
      trackOperations([op.id]);
      toast(`Traceroute añadido a la cola (op #${op.id})`);
    },
    onError: (e) => toast(`No se pudo añadir a la cola: ${e.message}`, { kind: "error" }),
  });
  const rescue = useMutation({
    mutationFn: importLegacyTraces,
    onSuccess: (r) => {
      toast(
        r.imported > 0
          ? `Rescatados ${r.imported} traceroutes antiguos del Registro (${r.skipped} omitidos)`
          : `Nada nuevo que rescatar (${r.scanned} revisados, ${r.skipped} ya estaban)`,
      );
      qc.invalidateQueries({ queryKey: ["traces"] });
    },
    onError: (e) => toast(`No se pudo importar: ${e.message}`, { kind: "error" }),
  });

  return (
    <div className="ws">
      <div className="toolbar" style={{ gap: 8 }}>
        <input
          className="input"
          placeholder="Buscar nodo…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          style={{ minWidth: 160 }}
        />
        <select className="input" value={period} onChange={(e) => setPeriod(e.target.value as typeof period)}>
          {PERIODS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
        <select className="input" value={gateway} onChange={(e) => setGateway(e.target.value)}>
          <option value="">Todas las pasarelas</option>
          {gateways.map((g) => (
            <option key={g.gateway_id} value={g.gateway_id}>
              {g.gateway_id}
            </option>
          ))}
        </select>
        <select className="input" value={result} onChange={(e) => setResult(e.target.value as typeof result)}>
          <option value="">Con y sin respuesta</option>
          <option value="ok">Con respuesta</option>
          <option value="none">Sin respuesta</option>
        </select>
        <select className="input" value={source} onChange={(e) => setSource(e.target.value as typeof source)}>
          <option value="">Activas y oídas</option>
          <option value="active">Solo activas</option>
          <option value="passive">Solo oídas en la malla</option>
        </select>
        <span style={{ flex: 1 }} />
        <span style={{ color: t.textDim, fontSize: 12 }}>{rows.length} trazas</span>
        {canOperate && (
          <button
            className="btn ghost"
            disabled={rescue.isPending}
            onClick={() => rescue.mutate()}
            title="Importa una vez los traceroutes que solo existían como entradas del Registro. Se recupera la ida; la vuelta no se guardaba."
          >
            {rescue.isPending ? "Rescatando…" : "⟲ Rescatar antiguos"}
          </button>
        )}
      </div>

      <div className="ws-scroll" style={{ overflowX: "auto" }}>
        {list.isLoading && <div className="empty">Cargando…</div>}
        {!list.isLoading && rows.length === 0 && (
          <div className="empty">
            No hay trazas con estos filtros. Lanza un traceroute desde el Inspector de un nodo
            {canOperate ? ", o pulsa «Rescatar antiguos» para traer los del Registro" : ""}.
          </div>
        )}
        {rows.length > 0 && (
          <table className="trace-table">
            <thead>
              <tr>
                <th>Cuándo</th>
                <th>Ruta</th>
                <th>Saltos</th>
                <th>Peor SNR</th>
                <th>Origen</th>
                <th>Resultado</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const worst = worstSnr(r);
                return (
                  <tr key={r.id}>
                    <td title={new Date(r.received_at).toLocaleString()}>{relativeTime(r.received_at)}</td>
                    <td>
                      <button className="linklike" onClick={() => onOpenNode(r.origin_id)}>
                        {nameOf(r.origin_id)}
                      </button>
                      {" → "}
                      <button className="linklike" onClick={() => onOpenNode(r.target_id)}>
                        {nameOf(r.target_id)}
                      </button>
                    </td>
                    <td className="mono">
                      {r.reached ? `${r.route.length}${r.route_back.length ? ` / ${r.route_back.length}` : ""}` : "—"}
                    </td>
                    <td className="mono" style={{ color: snrColor(worst) }}>
                      {worst != null ? `${worst} dB` : "—"}
                    </td>
                    <td>
                      <span className="chip">{r.source === "active" ? "Activa" : "Oída"}</span>
                      {r.gateway_id && <span style={{ color: t.textFaint, fontSize: 11 }}> {r.gateway_id}</span>}
                    </td>
                    <td style={{ color: r.reached ? "var(--ok)" : "var(--warn)" }}>
                      {r.reached ? "✓ Respuesta" : "Sin respuesta"}
                    </td>
                    <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                      <button
                        className="btn"
                        disabled={!r.reached}
                        onClick={() => onView3D(r.id)}
                        title={r.reached ? "Ver en el mapa 3D" : "Una traza sin respuesta no tiene recorrido"}
                      >
                        ◈ 3D
                      </button>{" "}
                      {canOperate && (
                        <button
                          className="btn ghost"
                          disabled={repeat.isPending}
                          onClick={() => repeat.mutate(r.target_id)}
                          title="Lanzar otro traceroute al mismo destino (inunda la malla hasta 5 saltos)"
                        >
                          ↻
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

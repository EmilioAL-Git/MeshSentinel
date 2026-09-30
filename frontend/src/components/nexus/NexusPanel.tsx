import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  dismissNexusPassiveCandidate,
  fetchGateways,
  fetchNexusMode,
  fetchNexusPassiveCandidates,
  scanForNexusNodes,
  setNexusMode,
  setNodeNexus,
  type NexusCandidateOut,
  type NexusPassiveCandidateOut,
} from "../../api/client";
import { NexusOperationsPanel } from "./NexusOperationsPanel";
import { NexusSettingsPanel } from "./NexusSettingsPanel";
import { NexusCatIcon } from "./NexusCatIcon";
import { toast } from "../shell/Toast";
import { t } from "../../tokens";

/**
 * JenTastic-Nexus (ADR 0027, §6-8 del encargo original): interruptor global
 * + detección de nodos JT.
 *
 * El flag es la primera comprobación de cualquier componente/servicio del
 * módulo (guard clause) — con el flag OFF, esta vista no pide ni muestra
 * NADA relacionado con Nexus salvo el propio interruptor (hace falta verlo
 * para poder encenderlo).
 *
 * La detección SOLO sugiere: nunca marca un nodo por sí sola. Cada
 * candidato requiere una confirmación explícita del operador (botón
 * "Marcar") — decisión repetida varias veces por el usuario en el encargo
 * ("nunca se activa por inferencia"); no hay atajo de "marcar todos".
 */
export function NexusPanel() {
  const queryClient = useQueryClient();
  const modeQuery = useQuery({ queryKey: ["nexus-mode"], queryFn: fetchNexusMode });
  const enabled = modeQuery.data?.enabled ?? false;

  const toggleMode = useMutation({
    mutationFn: (value: boolean) => setNexusMode(value),
    onSuccess: (data) => {
      queryClient.setQueryData(["nexus-mode"], data);
      toast(data.enabled ? "Modo Nexus/JenTastic activado" : "Modo Nexus/JenTastic desactivado");
    },
    onError: (err) => toast(err instanceof Error ? err.message : "No se pudo cambiar el modo", { kind: "error" }),
  });

  return (
    <div>
      <h2 style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
        <NexusCatIcon size={16} />
        JenTastic-Nexus
      </h2>
      <p style={{ color: t.textDim, fontSize: 12.5, maxWidth: 640, marginTop: 4 }}>
        Control de nodos con firmware JenTastic-Nexus por comandos de texto (ADR 0027). Con el
        modo desactivado, esta funcionalidad no existe en el resto de la aplicación: ni pestañas,
        ni marcado de nodos, ni comandos por la malla.
      </p>
      <label style={{ display: "inline-flex", alignItems: "center", gap: 8, marginTop: 10, cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={enabled}
          disabled={modeQuery.isLoading || toggleMode.isPending}
          onChange={(e) => toggleMode.mutate(e.target.checked)}
        />
        <NexusCatIcon size={14} />
        <span>Modo Nexus/JenTastic activado</span>
      </label>

      {enabled && <NexusSettingsPanel />}
      {enabled && <NexusDetection />}
      {enabled && <NexusPassiveDetection />}
      {enabled && <NexusOperationsPanel />}
    </div>
  );
}

function NexusDetection() {
  const queryClient = useQueryClient();
  const gatewaysQuery = useQuery({ queryKey: ["gateways"], queryFn: () => fetchGateways() });
  const gateways = (gatewaysQuery.data ?? []).filter((g) => g.status === "connected");
  const [gatewayId, setGatewayId] = useState<string>("");
  const [candidates, setCandidates] = useState<NexusCandidateOut[] | null>(null);

  const scanMutation = useMutation({
    mutationFn: () => scanForNexusNodes(gatewayId, 30),
    onSuccess: (data) => {
      setCandidates(data.candidates);
      if (data.candidates.length === 0) {
        toast("Ningún nodo JenTastic-Nexus respondió en esta pasarela");
      }
    },
    onError: (err) =>
      toast(err instanceof Error ? err.message.replace(/^HTTP \d+: /, "") : "No se pudo escanear", {
        kind: "error",
      }),
  });

  const markMutation = useMutation({
    mutationFn: (nodeId: string) => setNodeNexus(nodeId, true),
    onSuccess: (_data, nodeId) => {
      toast("Nodo marcado como JenTastic-Nexus");
      setCandidates((prev) => prev?.filter((c) => c.node_id !== nodeId) ?? null);
      queryClient.invalidateQueries({ queryKey: ["nodes"] });
    },
    onError: (err) => toast(err instanceof Error ? err.message : "No se pudo marcar", { kind: "error" }),
  });

  const discard = (nodeId: string) => setCandidates((prev) => prev?.filter((c) => c.node_id !== nodeId) ?? null);

  return (
    <div style={{ marginTop: "1.4rem" }}>
      <h3 style={{ fontSize: 13, textTransform: "uppercase", letterSpacing: "0.06em", color: t.textDim }}>
        Detección de nodos JT
      </h3>
      <p style={{ color: t.textFaint, fontSize: 11.5, maxWidth: 560, marginTop: 4 }}>
        Manda una difusión <code>/nexus INFO</code> por el canal Nexus/JenT (el gateway lo
        detecta solo, nunca por índice fijo) y escucha 30 s. Cada nodo que responda aparece como
        SUGERENCIA — no se marca nada hasta que lo confirmes.
      </p>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
        <select
          className="input"
          value={gatewayId}
          onChange={(e) => setGatewayId(e.target.value)}
          style={{ minWidth: 220 }}
        >
          <option value="">Elige una pasarela conectada…</option>
          {gateways.map((g) => (
            <option key={g.gateway_id} value={g.gateway_id}>
              {g.name || g.gateway_id} ({g.gateway_id})
            </option>
          ))}
        </select>
        <button
          className="btn"
          disabled={!gatewayId || scanMutation.isPending}
          onClick={() => scanMutation.mutate()}
        >
          {scanMutation.isPending ? "Buscando (30 s)…" : "Buscar nodos JT"}
        </button>
      </div>

      {candidates != null && (
        <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 12, fontSize: 12.5 }}>
          <thead>
            <tr style={{ textAlign: "left", color: t.textFaint, fontSize: 11 }}>
              <th style={{ padding: "4px 8px" }}>Nodo</th>
              <th style={{ padding: "4px 8px" }}>Versión</th>
              <th style={{ padding: "4px 8px" }}>Rol</th>
              <th style={{ padding: "4px 8px" }} />
            </tr>
          </thead>
          <tbody>
            {candidates.length === 0 && (
              <tr>
                <td colSpan={4} style={{ padding: "8px", color: t.textFaint }}>
                  Sin candidatos.
                </td>
              </tr>
            )}
            {candidates.map((c) => (
              <tr key={c.node_id} style={{ borderTop: `1px solid ${t.borderSubtle}` }}>
                <td className="mono" style={{ padding: "6px 8px" }}>
                  {c.marker ? `${c.marker} ` : ""}
                  {c.short_name ?? "—"} ({c.node_id})
                </td>
                <td style={{ padding: "6px 8px" }}>{c.version ?? "—"}</td>
                <td style={{ padding: "6px 8px" }}>{c.role ?? "—"}</td>
                <td style={{ padding: "6px 8px", whiteSpace: "nowrap" }}>
                  {c.already_marked ? (
                    <span className="chip">ya marcado</span>
                  ) : (
                    <span style={{ display: "inline-flex", gap: 6 }}>
                      <button
                        className="btn"
                        disabled={markMutation.isPending}
                        onClick={() => markMutation.mutate(c.node_id)}
                      >
                        Marcar
                      </button>
                      <button className="btn ghost" onClick={() => discard(c.node_id)}>
                        Descartar
                      </button>
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/**
 * Detección PASIVA (a diferencia de `NexusDetection`, no manda nada):
 * el backend escucha en vivo el tráfico que ya llega por el canal Nexus y
 * sugiere cualquier nodo cuyo texto tenga forma de respuesta Nexus, aunque
 * nadie le haya preguntado nada. Sondeo cada 5 s mientras la pestaña está
 * abierta — mismo criterio de "solo sugiere" que el escaneo activo:
 * "Marcar" es la única vía que escribe `nodes.is_nexus`.
 */
function NexusPassiveDetection() {
  const queryClient = useQueryClient();
  const candidatesQuery = useQuery({
    queryKey: ["nexus-passive-candidates"],
    queryFn: fetchNexusPassiveCandidates,
    refetchInterval: 5000,
  });
  const candidates = candidatesQuery.data ?? [];

  const markMutation = useMutation({
    mutationFn: (nodeId: string) => setNodeNexus(nodeId, true),
    onSuccess: (_data, nodeId) => {
      toast("Nodo marcado como JenTastic-Nexus");
      queryClient.setQueryData<NexusPassiveCandidateOut[]>(["nexus-passive-candidates"], (prev) =>
        prev?.map((c) => (c.node_id === nodeId ? { ...c, already_marked: true } : c))
      );
      queryClient.invalidateQueries({ queryKey: ["nodes"] });
    },
    onError: (err) => toast(err instanceof Error ? err.message : "No se pudo marcar", { kind: "error" }),
  });

  const dismissMutation = useMutation({
    mutationFn: (nodeId: string) => dismissNexusPassiveCandidate(nodeId),
    onSuccess: (_data, nodeId) => {
      queryClient.setQueryData<NexusPassiveCandidateOut[]>(["nexus-passive-candidates"], (prev) =>
        prev?.filter((c) => c.node_id !== nodeId)
      );
    },
    onError: (err) => toast(err instanceof Error ? err.message : "No se pudo descartar", { kind: "error" }),
  });

  return (
    <div style={{ marginTop: "1.4rem" }}>
      <h3 style={{ fontSize: 13, textTransform: "uppercase", letterSpacing: "0.06em", color: t.textDim }}>
        Detección pasiva de nodos JT
      </h3>
      <p style={{ color: t.textFaint, fontSize: 11.5, maxWidth: 560, marginTop: 4 }}>
        Sin mandar nada: observa el tráfico que ya llega por el canal Nexus y sugiere cualquier
        nodo cuyo texto tenga forma de respuesta Nexus (por ejemplo, dos nodos JT hablando entre
        sí, o alguien probando un comando desde el suyo). Igual que arriba, es solo SUGERENCIA.
      </p>

      <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 12, fontSize: 12.5 }}>
        <thead>
          <tr style={{ textAlign: "left", color: t.textFaint, fontSize: 11 }}>
            <th style={{ padding: "4px 8px" }}>Nodo</th>
            <th style={{ padding: "4px 8px" }}>Pasarela</th>
            <th style={{ padding: "4px 8px" }}>Comando visto</th>
            <th style={{ padding: "4px 8px" }}>Visto ×</th>
            <th style={{ padding: "4px 8px" }}>Última vez</th>
            <th style={{ padding: "4px 8px" }} />
          </tr>
        </thead>
        <tbody>
          {candidates.length === 0 && (
            <tr>
              <td colSpan={6} style={{ padding: "8px", color: t.textFaint }}>
                {candidatesQuery.isLoading ? "Cargando…" : "Sin candidatos todavía."}
              </td>
            </tr>
          )}
          {candidates.map((c) => (
            <tr key={c.node_id} style={{ borderTop: `1px solid ${t.borderSubtle}` }} title={c.sample_text}>
              <td className="mono" style={{ padding: "6px 8px" }}>{c.node_id}</td>
              <td style={{ padding: "6px 8px" }}>{c.gateway_id}</td>
              <td className="mono" style={{ padding: "6px 8px" }}>{c.command ?? "—"}</td>
              <td style={{ padding: "6px 8px" }}>{c.match_count}</td>
              <td style={{ padding: "6px 8px" }}>{new Date(c.last_seen_at).toLocaleTimeString()}</td>
              <td style={{ padding: "6px 8px", whiteSpace: "nowrap" }}>
                {c.already_marked ? (
                  <span className="chip">ya marcado</span>
                ) : (
                  <span style={{ display: "inline-flex", gap: 6 }}>
                    <button
                      className="btn"
                      disabled={markMutation.isPending}
                      onClick={() => markMutation.mutate(c.node_id)}
                    >
                      Marcar
                    </button>
                    <button
                      className="btn ghost"
                      disabled={dismissMutation.isPending}
                      onClick={() => dismissMutation.mutate(c.node_id)}
                    >
                      Descartar
                    </button>
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

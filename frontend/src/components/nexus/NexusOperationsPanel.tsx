import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createNexusOperation,
  displayName,
  fetchGateways,
  fetchNexusOperationResponses,
  fetchNexusOperations,
  fetchNexusSettings,
  fetchNodes,
  previewNexusOperation,
  type NexusOperationOut,
  type NexusOperationPreviewOut,
  type NexusOperationStatus,
  type NexusTargetKind,
} from "../../api/client";
import { toast } from "../shell/Toast";
import { t } from "../../tokens";
import { NexusArgsField } from "./NexusArgsField";
import { NexusCatalogBrowser } from "./NexusCatalogBrowser";
import { NexusCommandHint } from "./NexusCommandHint";

// Vocabulario de operador (M4.1, mismo criterio): nunca el vocabulario del
// pipeline de administración remota (modelo distinto — ver ADR 0027 §4).
export const STATUS_LABELS: Record<NexusOperationStatus, string> = {
  pending: "Pendiente",
  sent: "Enviado",
  confirmed: "Confirmado",
  no_response: "Sin respuesta",
};
export const STATUS_COLORS: Record<NexusOperationStatus, string> = {
  pending: "var(--text-faint)",
  sent: "var(--accent)",
  confirmed: "var(--ok)",
  no_response: "var(--crit)",
};

const TARGET_KINDS: { value: NexusTargetKind; label: string; needsValue: boolean; hint?: string }[] = [
  {
    value: "broadcast", label: "Difusión (toda la flota Nexus)", needsValue: false,
    hint: "Llega a todos los nodos Nexus del canal a la vez — cada uno responde por separado, se ven todas las respuestas debajo.",
  },
  { value: "local", label: "Local (la propia pasarela)", needsValue: false },
  { value: "node", label: "Nodo (-node, nombre corto)", needsValue: true },
  {
    value: "device", label: "Nodo (-device, node_id)", needsValue: true,
    hint: "⚠ el node_id puede cambiar al reflashear (firmware 2.8+) — si el nodo no responde, prueba con su nombre corto.",
  },
  { value: "mac", label: "MAC (-mac, 6 hex)", needsValue: true },
  {
    value: "group", label: "Grupo Nexus (-group)", needsValue: true,
    hint: "Grupo de radio del propio firmware (zona/salto) — distinto de los grupos de MeshSentinel. Varios nodos pueden responder, se ven todas las respuestas debajo.",
  },
];

/**
 * Formulario de creación + historial de la cola de operaciones (ADR 0027
 * §4). Previsualiza SIEMPRE antes de añadir a la cola (dry-run, mismo patrón que M2
 * "simular→CONFIRMAR"): un comando destructivo exige teclear el destino
 * para confirmar, igual que M1.3 con los SETs verificables.
 */
export function NexusOperationsPanel() {
  const queryClient = useQueryClient();
  const gatewaysQuery = useQuery({ queryKey: ["gateways"], queryFn: () => fetchGateways() });
  const gateways = (gatewaysQuery.data ?? []).filter((g) => g.status === "connected");
  const settingsQuery = useQuery({ queryKey: ["nexus-settings"], queryFn: fetchNexusSettings });
  const settings = settingsQuery.data;
  // Confirmación reforzada de difusión destructiva (ADR 0027): en vez de
  // teclear la palabra "BROADCAST", el operador teclea el número REAL de
  // nodos marcados como Nexus ahora mismo — obliga a comprobar el alcance
  // real antes de confirmar, no solo a copiar una palabra fija. Es un
  // recuento informativo (nodos marcados en MeshSentinel), no una garantía
  // de cuántos nodos recibirán de verdad el broadcast del canal.
  const nexusCountQuery = useQuery({
    queryKey: ["nodes", "nexus-count"],
    queryFn: () => fetchNodes({ nexus: true }),
  });
  const nexusNodeCount = nexusCountQuery.data?.length;

  // Sugerencias para los argumentos con forma de id de nodo (FAV/IGNORE/ZH/
  // WATCH, ver NexusArgsField) — toda la flota, no solo la marcada Nexus.
  const allNodesQuery = useQuery({ queryKey: ["nodes", "all-for-nexus-args"], queryFn: () => fetchNodes() });
  const nodeOptions = (allNodesQuery.data ?? []).map((s) => ({ node_id: s.node.node_id, label: displayName(s.node) }));

  const [gatewayId, setGatewayId] = useState("");
  const [targetKind, setTargetKind] = useState<NexusTargetKind>("broadcast");
  const [targetValue, setTargetValue] = useState("");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState<string[]>([]);
  const [preview, setPreview] = useState<NexusOperationPreviewOut | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [appliedDefaults, setAppliedDefaults] = useState(false);

  // Ajustes (ADR 0027 §13): destino/pasarela por defecto — solo se aplican
  // UNA vez, al cargar, y nunca pisan lo que el operador ya haya tocado.
  if (settings && !appliedDefaults) {
    setAppliedDefaults(true);
    if (settings.default_target_kind !== "broadcast") setTargetKind(settings.default_target_kind);
    if (settings.default_gateway_id) setGatewayId(settings.default_gateway_id);
  }

  const kindDef = TARGET_KINDS.find((k) => k.value === targetKind)!;
  const body = {
    gateway_id: gatewayId,
    command: command.trim().toUpperCase(),
    args,
    target_kind: targetKind,
    target_value: kindDef.needsValue ? targetValue.trim() : null,
  };
  const canBuild = gatewayId !== "" && command.trim() !== "" && (!kindDef.needsValue || targetValue.trim() !== "");

  const previewMutation = useMutation({
    mutationFn: () => previewNexusOperation(body),
    onSuccess: (data) => {
      setPreview(data);
      setConfirmText("");
    },
    onError: (err) => {
      setPreview(null);
      toast(err instanceof Error ? err.message.replace(/^HTTP \d+: /, "") : "No se pudo construir", {
        kind: "error",
      });
    },
  });

  const createMutation = useMutation({
    mutationFn: () => createNexusOperation(body),
    onSuccess: () => {
      toast("Operación añadida a la cola");
      setPreview(null);
      setConfirmText("");
      setArgs([]);
      queryClient.invalidateQueries({ queryKey: ["nexus-operations"] });
    },
    onError: (err) =>
      toast(err instanceof Error ? err.message.replace(/^HTTP \d+: /, "") : "No se pudo añadir a la cola", {
        kind: "error",
      }),
  });

  const isBroadcast = targetKind === "broadcast";
  // En difusión, el recuento tiene que haber cargado ya — nunca se deja
  // confirmar "a ciegas" mientras la cifra real está en duda.
  const confirmPhrase = kindDef.needsValue
    ? targetValue.trim()
    : isBroadcast
      ? (nexusNodeCount != null ? String(nexusNodeCount) : null)
      : "BROADCAST";
  const needsTypedConfirm = preview?.destructive ?? false;
  const canQueue =
    preview != null &&
    (!needsTypedConfirm || (confirmPhrase != null && confirmText.trim() === confirmPhrase));

  return (
    <div style={{ marginTop: "1.4rem" }}>
      <h3 style={{ fontSize: 13, textTransform: "uppercase", letterSpacing: "0.06em", color: t.textDim }}>
        Operaciones
      </h3>
      <p style={{ color: t.textFaint, fontSize: 11.5, maxWidth: 620, marginTop: 4 }}>
        Cualquier comando del catálogo, con el mismo espaciado y direccionamiento validados en el
        núcleo del módulo. Siempre se previsualiza el texto exacto antes de añadir a la cola; los comandos
        destructivos piden teclear el destino para confirmar.
      </p>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8, alignItems: "center" }}>
        <select className="input" value={gatewayId} onChange={(e) => { setGatewayId(e.target.value); setPreview(null); }}>
          <option value="">Pasarela…</option>
          {gateways.map((g) => (
            <option key={g.gateway_id} value={g.gateway_id}>{g.name || g.gateway_id}</option>
          ))}
        </select>
        <select
          className="input"
          value={targetKind}
          onChange={(e) => { setTargetKind(e.target.value as NexusTargetKind); setPreview(null); }}
        >
          {TARGET_KINDS.map((k) => (
            <option key={k.value} value={k.value}>{k.label}</option>
          ))}
        </select>
        {kindDef.hint && (
          <span style={{ color: t.textFaint, fontSize: 10.5, maxWidth: 260 }}>{kindDef.hint}</span>
        )}
        {kindDef.needsValue && (
          <input
            className="input"
            style={{ width: 140 }}
            placeholder={targetKind === "mac" ? "6 hex" : targetKind === "group" ? "grupo" : "nombre corto"}
            value={targetValue}
            onChange={(e) => { setTargetValue(e.target.value); setPreview(null); }}
          />
        )}
        <input
          className="input mono"
          style={{ width: 140 }}
          placeholder="COMANDO"
          value={command}
          onChange={(e) => { setCommand(e.target.value); setArgs([]); setPreview(null); }}
        />
        <NexusArgsField
          command={command}
          args={args}
          onChange={(next) => { setArgs(next); setPreview(null); }}
          nodeOptions={nodeOptions}
        />
        <button
          className="btn"
          disabled={!canBuild || previewMutation.isPending}
          onClick={() => previewMutation.mutate()}
        >
          Previsualizar
        </button>
      </div>
      <NexusCommandHint command={command} />
      <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
        <NexusCatalogBrowser onSelect={(name, nextArgs) => { setCommand(name); setArgs(nextArgs); setPreview(null); }} />
        {settings && settings.pinned_nodes.length > 0 && kindDef.needsValue && targetKind === "node" && (
          <>
            <span style={{ color: t.textFaint, fontSize: 10.5 }}>fijados:</span>
            {settings.pinned_nodes.map((n) => (
              <button
                key={n.short_name}
                className="chip"
                style={{ cursor: "pointer" }}
                onClick={() => { setTargetValue(n.short_name); setPreview(null); }}
              >
                {n.label}
              </button>
            ))}
          </>
        )}
        {settings && settings.templates.length > 0 && (
          <>
            <span style={{ color: t.textFaint, fontSize: 10.5 }}>plantillas:</span>
            {settings.templates.map((tpl) => (
              <button
                key={tpl.label + tpl.command}
                className="chip"
                style={{ cursor: "pointer" }}
                title={`${tpl.command} ${tpl.args}`}
                onClick={() => {
                  setCommand(tpl.command);
                  setArgs(tpl.args.trim() ? tpl.args.trim().split(/\s+/) : []);
                  setPreview(null);
                }}
              >
                {tpl.label}
              </button>
            ))}
          </>
        )}
      </div>

      {preview && (
        <div className="panel" style={{ marginTop: 10, padding: "0.6rem 0.8rem" }}>
          <div className="mono" style={{ fontSize: 13 }}>{preview.text}</div>
          <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
            {preview.destructive && <span className="chip" style={{ color: "var(--crit)", borderColor: "var(--crit)" }}>destructivo</span>}
            {preview.requires_save && <span className="chip" style={{ color: "var(--warn)", borderColor: "var(--warn)" }}>requiere SAVE</span>}
            {preview.busy_seconds > 0 && (
              <span className="chip">deja el nodo ocupado {preview.busy_seconds}s</span>
            )}
          </div>
          {needsTypedConfirm && isBroadcast && (
            <div style={{ marginTop: 8 }}>
              <label className="microlabel">
                {confirmPhrase == null ? (
                  "Comando destructivo en difusión — comprobando cuántos nodos Nexus hay marcados…"
                ) : (
                  <>
                    Comando destructivo en difusión — afecta a{" "}
                    <strong className="mono">{confirmPhrase}</strong> nodo(s) marcado(s) como Nexus.
                    Escribe <strong className="mono">{confirmPhrase}</strong> para confirmar.
                  </>
                )}
              </label>
              <input
                className="input"
                style={{ display: "block", marginTop: 4, width: 220 }}
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                disabled={confirmPhrase == null}
              />
            </div>
          )}
          {needsTypedConfirm && !isBroadcast && (
            <div style={{ marginTop: 8 }}>
              <label className="microlabel">
                Comando destructivo — escribe <strong className="mono">{confirmPhrase}</strong> para confirmar
              </label>
              <input
                className="input"
                style={{ display: "block", marginTop: 4, width: 220 }}
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
              />
            </div>
          )}
          <button
            className="btn primary"
            style={{ marginTop: 8 }}
            disabled={!canQueue || createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            Añadir a la cola
          </button>
        </div>
      )}

      {gatewayId && <OperationsHistory gatewayId={gatewayId} />}
    </div>
  );
}

const FANOUT_KINDS_FOR_NOTIFY = new Set(["broadcast", "group"]);

function OperationsHistory({ gatewayId }: { gatewayId: string }) {
  const query = useQuery({
    queryKey: ["nexus-operations", gatewayId],
    queryFn: () => fetchNexusOperations(gatewayId, undefined, 100),
    refetchInterval: 3000,
  });
  const ops = query.data ?? [];
  const settingsQuery = useQuery({ queryKey: ["nexus-settings"], queryFn: fetchNexusSettings });

  // Ajuste "avisar cuando termine una difusión" (ADR 0027 §13): sin evento
  // WS dedicado para operaciones Nexus (ADR 0027 §4, el gateway nunca
  // reporta resultado) — se detecta por comparación entre polls, un toast
  // por operación, nunca repetido.
  const notifiedRef = useRef<Set<number>>(new Set());
  useEffect(() => {
    if (!settingsQuery.data?.notify_on_broadcast_complete) return;
    for (const op of ops) {
      if (!FANOUT_KINDS_FOR_NOTIFY.has(op.target_kind)) continue;
      if (op.status !== "confirmed" && op.status !== "no_response") continue;
      if (notifiedRef.current.has(op.id)) continue;
      notifiedRef.current.add(op.id);
      toast(
        op.status === "confirmed"
          ? `Difusión «${op.text}» terminada: respondieron nodos`
          : `Difusión «${op.text}» terminada: sin respuestas`,
        { kind: op.status === "confirmed" ? "ok" : "error" },
      );
    }
  }, [ops, settingsQuery.data?.notify_on_broadcast_complete]);

  return (
    <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 12, fontSize: 12 }}>
      <thead>
        <tr style={{ textAlign: "left", color: t.textFaint, fontSize: 11 }}>
          <th style={{ padding: "4px 8px" }}>Comando</th>
          <th style={{ padding: "4px 8px" }}>Estado</th>
          <th style={{ padding: "4px 8px" }}>Respuesta</th>
        </tr>
      </thead>
      <tbody>
        {ops.length === 0 && (
          <tr>
            <td colSpan={3} style={{ padding: "8px", color: t.textFaint }}>
              Sin operaciones todavía en esta pasarela.
            </td>
          </tr>
        )}
        {ops.map((op) => (
          <OperationRow key={op.id} op={op} />
        ))}
      </tbody>
    </table>
  );
}

// Difusión/grupo (ADR 0027 §11): pedido explícito del usuario — un comando
// mandado a toda la malla Nexus del canal debe dejar ver a CADA nodo
// responder por separado, no un único estado agregado.
const FANOUT_KINDS = new Set(["broadcast", "group"]);

function OperationRow({ op }: { op: NexusOperationOut }) {
  const [expanded, setExpanded] = useState(false);
  const isFanout = FANOUT_KINDS.has(op.target_kind);
  const canExpand = isFanout ? op.status !== "pending" : !!op.response_text;
  return (
    <>
      <tr style={{ borderTop: `1px solid ${t.borderSubtle}`, cursor: canExpand ? "pointer" : undefined }}
        onClick={() => canExpand && setExpanded((v) => !v)}
      >
        <td className="mono" style={{ padding: "6px 8px" }}>{op.text}</td>
        <td style={{ padding: "6px 8px", color: STATUS_COLORS[op.status] }}>{STATUS_LABELS[op.status]}</td>
        <td className="mono" style={{ padding: "6px 8px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 260 }}>
          {isFanout ? "ver respuestas por nodo →" : (op.response_text ?? "—")}
        </td>
      </tr>
      {expanded && isFanout && <FanoutResponses opId={op.id} />}
      {expanded && !isFanout && op.response_text && (
        <tr style={{ background: "var(--surface-2)" }}>
          <td colSpan={3} style={{ padding: "6px 8px" }}>
            <pre className="mono" style={{ whiteSpace: "pre-wrap", margin: 0, fontSize: 11 }}>{op.response_text}</pre>
            {op.response_kind === "structured" && op.response_data && (
              <pre className="mono" style={{ whiteSpace: "pre-wrap", marginTop: 6, fontSize: 11, color: t.textDim }}>
                {JSON.stringify(op.response_data, null, 2)}
              </pre>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

function FanoutResponses({ opId }: { opId: number }) {
  const query = useQuery({
    queryKey: ["nexus-operation-responses", opId],
    queryFn: () => fetchNexusOperationResponses(opId),
    refetchInterval: 3000,
  });
  const responses = query.data ?? [];
  return (
    <tr style={{ background: "var(--surface-2)" }}>
      <td colSpan={3} style={{ padding: "6px 8px" }}>
        {responses.length === 0 && (
          <div style={{ color: t.textFaint, fontSize: 11.5 }}>Ningún nodo ha respondido todavía.</div>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {responses.map((r) => (
            <div key={r.id} style={{ fontSize: 11.5 }}>
              <div style={{ display: "flex", gap: 6, alignItems: "baseline" }}>
                <span className="mono" style={{ color: t.accent }}>{r.from_node_id}</span>
                <span className="mono" style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {r.response_text}
                </span>
              </div>
              {r.response_kind === "structured" && r.response_data && (
                <pre className="mono" style={{ whiteSpace: "pre-wrap", marginTop: 2, fontSize: 10.5, color: t.textDim }}>
                  {JSON.stringify(r.response_data, null, 2)}
                </pre>
              )}
            </div>
          ))}
        </div>
      </td>
    </tr>
  );
}

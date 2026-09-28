import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createNexusOperation,
  fetchGateways,
  fetchNexusOperationResponses,
  fetchNexusOperations,
  previewNexusOperation,
  type NexusOperationOut,
  type NexusOperationPreviewOut,
  type NexusOperationStatus,
  type NexusTargetKind,
} from "../../api/client";
import { toast } from "../shell/Toast";
import { t } from "../../tokens";
import { NexusCatalogBrowser } from "./NexusCatalogBrowser";

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
  { value: "mac", label: "MAC (-mac, 6 hex)", needsValue: true },
  {
    value: "group", label: "Grupo Nexus (-group)", needsValue: true,
    hint: "Grupo de radio del propio firmware (zona/salto) — distinto de los grupos de MeshSentinel. Varios nodos pueden responder, se ven todas las respuestas debajo.",
  },
];

/**
 * Formulario de creación + historial de la cola de operaciones (ADR 0027
 * §4). Previsualiza SIEMPRE antes de encolar (dry-run, mismo patrón que M2
 * "simular→CONFIRMAR"): un comando destructivo exige teclear el destino
 * para confirmar, igual que M1.3 con los SETs verificables.
 */
export function NexusOperationsPanel() {
  const queryClient = useQueryClient();
  const gatewaysQuery = useQuery({ queryKey: ["gateways"], queryFn: () => fetchGateways() });
  const gateways = (gatewaysQuery.data ?? []).filter((g) => g.status === "connected");

  const [gatewayId, setGatewayId] = useState("");
  const [targetKind, setTargetKind] = useState<NexusTargetKind>("broadcast");
  const [targetValue, setTargetValue] = useState("");
  const [command, setCommand] = useState("");
  const [argsInput, setArgsInput] = useState("");
  const [preview, setPreview] = useState<NexusOperationPreviewOut | null>(null);
  const [confirmText, setConfirmText] = useState("");

  const kindDef = TARGET_KINDS.find((k) => k.value === targetKind)!;
  const args = argsInput.trim() ? argsInput.trim().split(/\s+/) : [];
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
      toast("Operación encolada");
      setPreview(null);
      setConfirmText("");
      setArgsInput("");
      queryClient.invalidateQueries({ queryKey: ["nexus-operations"] });
    },
    onError: (err) =>
      toast(err instanceof Error ? err.message.replace(/^HTTP \d+: /, "") : "No se pudo encolar", {
        kind: "error",
      }),
  });

  const confirmPhrase = kindDef.needsValue ? targetValue.trim() : "BROADCAST";
  const needsTypedConfirm = preview?.destructive ?? false;
  const canQueue = preview != null && (!needsTypedConfirm || confirmText.trim() === confirmPhrase);

  return (
    <div style={{ marginTop: "1.4rem" }}>
      <h3 style={{ fontSize: 13, textTransform: "uppercase", letterSpacing: "0.06em", color: t.textDim }}>
        Operaciones
      </h3>
      <p style={{ color: t.textFaint, fontSize: 11.5, maxWidth: 620, marginTop: 4 }}>
        Cualquier comando del catálogo, con el mismo espaciado y direccionamiento validados en el
        núcleo del módulo. Siempre se previsualiza el texto exacto antes de encolar; los comandos
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
          onChange={(e) => { setCommand(e.target.value); setPreview(null); }}
        />
        <input
          className="input mono"
          style={{ width: 200 }}
          placeholder="argumentos (espacio)"
          value={argsInput}
          onChange={(e) => { setArgsInput(e.target.value); setPreview(null); }}
        />
        <button
          className="btn"
          disabled={!canBuild || previewMutation.isPending}
          onClick={() => previewMutation.mutate()}
        >
          Previsualizar
        </button>
      </div>
      <div style={{ marginTop: 6 }}>
        <NexusCatalogBrowser onSelect={(name) => { setCommand(name); setPreview(null); }} />
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
          {needsTypedConfirm && (
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
            Encolar
          </button>
        </div>
      )}

      {gatewayId && <OperationsHistory gatewayId={gatewayId} />}
    </div>
  );
}

function OperationsHistory({ gatewayId }: { gatewayId: string }) {
  const query = useQuery({
    queryKey: ["nexus-operations", gatewayId],
    queryFn: () => fetchNexusOperations(gatewayId, undefined, 100),
    refetchInterval: 3000,
  });
  const ops = query.data ?? [];

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

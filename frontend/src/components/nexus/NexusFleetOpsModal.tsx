import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createNexusOperation,
  createNexusOperationBatch,
  displayName,
  fetchGateways,
  fetchNexusSettings,
  fetchNodes,
  previewNexusOperation,
  type GatewayOut,
  type NexusOperationPreviewOut,
  type NodeSummaryOut,
} from "../../api/client";
import { toast } from "../shell/Toast";
import { t } from "../../tokens";
import { NexusArgsField } from "./NexusArgsField";
import { NexusCatalogBrowser } from "./NexusCatalogBrowser";
import { NexusQuickActions } from "./NexusQuickActions";
import { NexusCommandHint } from "./NexusCommandHint";
import { NexusFeed } from "./NexusFeed";

type Scope = "single" | "broadcast" | "selected";

const INTERVAL_DEFAULT = 5;
const INTERVAL_MIN = 1;
const INTERVAL_MAX = 60;

/**
 * Consola "Operaciones Nexus" (pantalla completa, pensada para quedarse
 * abierta): arriba el chat del canal Nexus con lo enviado, lo que contestan
 * los nodos y su interpretación (`NexusFeed`); abajo el compositor, mismo
 * núcleo que `NexusOperationsPanel` de Ajustes (previsualizar→confirmar→
 * añadir a la cola) con el alcance como primera decisión — un nodo, toda la
 * flota (difusión), o los nodos seleccionados en Flota (una operación
 * `-node` por cada uno, espaciadas). No se cierra al enviar: se queda para
 * ver las respuestas llegar.
 */
export function NexusFleetOpsModal({
  onClose,
  allSummaries,
  checkedIds,
  embedded = false,
}: {
  /** Integrada en una vista (Trabajos): sin overlay, sin Esc, ocupa el espacio que le dé el padre. */
  embedded?: boolean;
  onClose: () => void;
  allSummaries: NodeSummaryOut[];
  checkedIds: Set<string>;
}) {
  const queryClient = useQueryClient();
  const gatewaysQuery = useQuery({ queryKey: ["gateways"], queryFn: () => fetchGateways() });
  const gateways = (gatewaysQuery.data ?? []).filter((g: GatewayOut) => g.status === "connected");

  const byId = useMemo(() => new Map(allSummaries.map((s) => [s.node.node_id, s])), [allSummaries]);
  const selectedShortNames = useMemo(() => {
    const names: string[] = [];
    let missing = 0;
    for (const id of checkedIds) {
      const sn = byId.get(id)?.node.short_name;
      if (sn) names.push(sn);
      else missing++;
    }
    return { names, missing };
  }, [checkedIds, byId]);

  const [scope, setScope] = useState<Scope>(checkedIds.size > 0 ? "selected" : "single");
  const [gatewayId, setGatewayId] = useState("");
  const [singleTarget, setSingleTarget] = useState("");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState<string[]>([]);
  const [intervalSeconds, setIntervalSeconds] = useState(INTERVAL_DEFAULT);
  const [preview, setPreview] = useState<NexusOperationPreviewOut | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [showRaw, setShowRaw] = useState(true);
  const [showNoise, setShowNoise] = useState(true);

  // Pasarela por defecto: la de los ajustes, o la única conectada.
  const settingsQuery = useQuery({ queryKey: ["nexus-settings"], queryFn: fetchNexusSettings });
  useEffect(() => {
    if (gatewayId) return;
    const preferred = settingsQuery.data?.default_gateway_id;
    if (preferred && gateways.some((g) => g.gateway_id === preferred)) setGatewayId(preferred);
    else if (gateways.length === 1) setGatewayId(gateways[0]!.gateway_id);
  }, [gatewayId, gateways, settingsQuery.data]);

  // Esc cierra la consola.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (!embedded && e.key === "Escape" && tag !== "INPUT" && tag !== "SELECT" && tag !== "TEXTAREA") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Sugerencias para los argumentos con forma de id de nodo (FAV/IGNORE/ZH/
  // WATCH, ver NexusArgsField) — toda la flota conocida, no solo la
  // marcada Nexus (el id afectado puede ser cualquier nodo de la malla).
  const nodeOptions = useMemo(
    () => allSummaries.map((s) => ({ node_id: s.node.node_id, label: displayName(s.node) })),
    [allSummaries],
  );

  // Recuento en vivo de nodos marcados Nexus — solo hace falta para
  // reforzar la confirmación de un destructivo en difusión (mismo criterio
  // que NexusOperationsPanel.tsx).
  const nexusCountQuery = useQuery({
    queryKey: ["nodes", "nexus-count"],
    queryFn: () => fetchNodes({ nexus: true }),
    enabled: scope === "broadcast",
  });
  const nexusNodeCount = nexusCountQuery.data?.length;

  const previewTargetKind = scope === "broadcast" ? "broadcast" : "node";
  const previewTargetValue = scope === "broadcast" ? null : scope === "single" ? singleTarget.trim() : selectedShortNames.names[0];

  const canBuild =
    gatewayId !== "" &&
    command.trim() !== "" &&
    (scope === "broadcast" ||
      (scope === "single" && singleTarget.trim() !== "") ||
      (scope === "selected" && selectedShortNames.names.length > 0));

  const previewMutation = useMutation({
    mutationFn: (override?: { command: string; args: string[] }) =>
      previewNexusOperation({
        gateway_id: gatewayId,
        command: (override?.command ?? command).trim().toUpperCase(),
        args: override?.args ?? args,
        target_kind: previewTargetKind,
        target_value: previewTargetValue,
      }),
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
    mutationFn: async () => {
      if (scope === "selected") {
        return createNexusOperationBatch({
          gateway_id: gatewayId,
          command: command.trim().toUpperCase(),
          args,
          target_values: selectedShortNames.names,
          interval_seconds: intervalSeconds,
        });
      }
      return createNexusOperation({
        gateway_id: gatewayId,
        command: command.trim().toUpperCase(),
        args,
        target_kind: scope === "broadcast" ? "broadcast" : "node",
        target_value: scope === "broadcast" ? null : singleTarget.trim(),
      });
    },
    onSuccess: (data) => {
      const n = Array.isArray(data) ? data.length : 1;
      toast(n > 1 ? `${n} comandos en ejecución` : "Comando en ejecución");
      queryClient.invalidateQueries({ queryKey: ["nexus-operations"] });
      queryClient.invalidateQueries({ queryKey: ["nexus-conversation"] });
      setPreview(null);
      setConfirmText("");
    },
    onError: (err) =>
      toast(err instanceof Error ? err.message.replace(/^HTTP \d+: /, "") : "No se pudo añadir a la cola", {
        kind: "error",
      }),
  });

  const needsTypedConfirm = preview?.destructive ?? false;
  const confirmPhrase =
    scope === "single"
      ? singleTarget.trim()
      : scope === "selected"
        ? String(selectedShortNames.names.length)
        : nexusNodeCount != null
          ? String(nexusNodeCount)
          : null;
  const canQueue =
    preview != null &&
    (!needsTypedConfirm || (confirmPhrase != null && confirmText.trim() === confirmPhrase));

  const resetPreview = () => setPreview(null);

  return (
    <div
      style={
        embedded
          ? {
              height: "calc(100vh - 190px)", minHeight: 480, background: "var(--chassis)",
              display: "flex", flexDirection: "column", border: "1px solid var(--border)", borderRadius: 6, overflow: "hidden",
            }
          : {
              position: "fixed", inset: 0, zIndex: 1000, background: "var(--chassis)",
              display: "flex", flexDirection: "column",
            }
      }
    >
      <div className="panel-head" style={{ gap: 12 }}>
        <span className="panel-title">🐱 Operaciones Nexus</span>
        <span style={{ color: t.textFaint, fontSize: 11 }}>canal Nexus en directo</span>
        <label
          title="Con el texto crudo apagado, las respuestas interpretadas muestran solo la frase. Las no interpretadas siempre enseñan su texto."
          style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11.5, color: t.textDim, marginLeft: "auto" }}
        >
          <input type="checkbox" checked={showRaw} onChange={(e) => setShowRaw(e.target.checked)} />
          texto crudo
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11.5, color: t.textDim }}>
          <input type="checkbox" checked={showNoise} onChange={(e) => setShowNoise(e.target.checked)} />
          otros mensajes del canal
        </label>
        <button className="btn ghost" style={{ padding: "0.1rem 0.5rem", fontSize: 11 }} onClick={onClose} title={embedded ? "Volver a Trabajos" : "Cerrar (Esc)"}>
          ✕
        </button>
      </div>

      <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
      <div
        style={{
          flex: 1, minWidth: 0, background: t.surface, padding: "0.8rem 1rem",
          overflowY: "auto",
        }}
      >
      <div style={{ display: "flex", flexWrap: "wrap", gap: 18, alignItems: "flex-start" }}>
      <div style={{ flex: "1.4 1 440px", minWidth: 0 }}>
        <NexusQuickActions
          nodeOptions={nodeOptions}
          disabledReason={
            gatewayId === "" ? "elige una pasarela"
            : scope === "single" && singleTarget.trim() === "" ? "indica el nombre corto del nodo"
            : scope === "selected" && selectedShortNames.names.length === 0 ? "selecciona nodos en Flota"
            : null
          }
          onSelect={(name, nextArgs) => { setCommand(name); setArgs(nextArgs); resetPreview(); }}
          onRun={(name, nextArgs) => {
            setCommand(name); setArgs(nextArgs);
            const ready = gatewayId !== "" && (scope === "broadcast"
              || (scope === "single" && singleTarget.trim() !== "")
              || (scope === "selected" && selectedShortNames.names.length > 0));
            if (ready) previewMutation.mutate({ command: name, args: nextArgs });
            else { resetPreview(); toast("Elige pasarela y destino y pulsa «Previsualizar»", { kind: "error" }); }
          }}
        />
      </div>
      <div style={{ flex: "1 1 380px", minWidth: 0, display: "flex", flexDirection: "column", gap: 10 }}>
        <div>
          <label className="microlabel">Alcance</label>
          <div style={{ display: "flex", gap: 6, marginTop: 4, flexWrap: "wrap" }}>
            <button
              className={`btn ${scope === "single" ? "primary" : "ghost"}`}
              onClick={() => { setScope("single"); resetPreview(); }}
            >
              Un solo nodo
            </button>
            <button
              className={`btn ${scope === "selected" ? "primary" : "ghost"}`}
              disabled={checkedIds.size === 0}
              title={checkedIds.size === 0 ? "Solo disponible si se abre con nodos seleccionados" : undefined}
              onClick={() => { setScope("selected"); resetPreview(); }}
            >
              Seleccionados ({checkedIds.size})
            </button>
            <button
              className={`btn ${scope === "broadcast" ? "primary" : "ghost"}`}
              onClick={() => { setScope("broadcast"); resetPreview(); }}
            >
              Toda la flota (difusión)
            </button>
          </div>
          {scope === "selected" && selectedShortNames.missing > 0 && (
            <p style={{ color: "var(--warn)", fontSize: 11, marginTop: 4 }}>
              {selectedShortNames.missing} nodo(s) seleccionado(s) sin nombre corto conocido — se excluyen del envío.
            </p>
          )}
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <select className="input" value={gatewayId} onChange={(e) => { setGatewayId(e.target.value); resetPreview(); }}>
            <option value="">Pasarela…</option>
            {gateways.map((g) => (
              <option key={g.gateway_id} value={g.gateway_id}>{g.name || g.gateway_id}</option>
            ))}
          </select>
          {scope === "single" && (
            <>
              <input
                className="input"
                style={{ width: 160 }}
                placeholder="nombre corto"
                value={singleTarget}
                onChange={(e) => { setSingleTarget(e.target.value); resetPreview(); }}
                list="nexus-fleet-ops-nodes"
              />
              <datalist id="nexus-fleet-ops-nodes">
                {allSummaries
                  .filter((s) => s.node.is_nexus && s.node.short_name)
                  .map((s) => (
                    <option key={s.node.node_id} value={s.node.short_name!}>
                      {displayName(s.node)}
                    </option>
                  ))}
              </datalist>
            </>
          )}
          {scope === "selected" && (
            <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11.5, color: t.textDim }}>
              intervalo entre envíos
              <input
                className="input"
                type="number"
                style={{ width: 64 }}
                min={INTERVAL_MIN}
                max={INTERVAL_MAX}
                value={intervalSeconds}
                onChange={(e) => setIntervalSeconds(Math.min(INTERVAL_MAX, Math.max(INTERVAL_MIN, Number(e.target.value) || INTERVAL_DEFAULT)))}
              />
              s
            </label>
          )}
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <input
            className="input mono"
            style={{ width: 140 }}
            placeholder="COMANDO"
            value={command}
            onChange={(e) => { setCommand(e.target.value); setArgs([]); resetPreview(); }}
          />
          <NexusArgsField
            command={command}
            args={args}
            onChange={(next) => { setArgs(next); resetPreview(); }}
            nodeOptions={nodeOptions}
          />
          <button className="btn" disabled={!canBuild || previewMutation.isPending} onClick={() => previewMutation.mutate(undefined)}>
            Previsualizar
          </button>
        </div>
        <NexusCommandHint command={command} />

        <div>
          <NexusCatalogBrowser
            nodeOptions={nodeOptions}
            onSelect={(name, nextArgs) => { setCommand(name); setArgs(nextArgs); resetPreview(); }}
          />
        </div>

        {preview && (
          <div className="panel" style={{ padding: "0.6rem 0.8rem" }}>
            <div className="mono" style={{ fontSize: 13 }}>{preview.text}</div>
            {scope === "selected" && (
              <p style={{ color: t.textFaint, fontSize: 11, marginTop: 4 }}>
                Ejemplo con el primer nodo — se repite, uno por uno (mismo comando, `-node` propio), para:{" "}
                {selectedShortNames.names.join(", ")} — espaciado {intervalSeconds}s entre envíos.
              </p>
            )}
            <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
              {preview.destructive && <span className="chip" style={{ color: "var(--crit)", borderColor: "var(--crit)" }}>destructivo</span>}
              {preview.requires_save && <span className="chip" style={{ color: "var(--warn)", borderColor: "var(--warn)" }}>requiere SAVE</span>}
              {preview.busy_seconds > 0 && <span className="chip">deja el nodo ocupado {preview.busy_seconds}s</span>}
            </div>
            {needsTypedConfirm && (
              <div style={{ marginTop: 8 }}>
                <label className="microlabel">
                  {confirmPhrase == null ? (
                    "Comando destructivo — comprobando el alcance…"
                  ) : scope === "single" ? (
                    <>Comando destructivo — escribe <strong className="mono">{confirmPhrase}</strong> para confirmar</>
                  ) : scope === "selected" ? (
                    <>Comando destructivo — afecta a <strong className="mono">{confirmPhrase}</strong> nodo(s) seleccionado(s). Escribe <strong className="mono">{confirmPhrase}</strong> para confirmar.</>
                  ) : (
                    <>Comando destructivo en difusión — afecta a <strong className="mono">{confirmPhrase}</strong> nodo(s) marcado(s) como Nexus. Escribe <strong className="mono">{confirmPhrase}</strong> para confirmar.</>
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
            <button
              className="btn primary"
              style={{ marginTop: 8 }}
              disabled={!canQueue || createMutation.isPending}
              onClick={() => createMutation.mutate()}
            >
              {scope === "selected" ? `Ejecutar comando (${selectedShortNames.names.length})` : "Ejecutar comando"}
            </button>
          </div>
        )}
      </div>
      </div>
      </div>
      <aside
        style={{
          width: "min(440px, 38vw)", minWidth: 280, flexShrink: 0, minHeight: 0,
          display: "flex", flexDirection: "column", borderLeft: "1px solid var(--border)",
          background: "var(--chassis)",
        }}
      >
        <div className="panel-head">
          <span className="panel-title">Canal Nexus</span>
        </div>
        <NexusFeed showRaw={showRaw} showNoise={showNoise} />
      </aside>
      </div>
    </div>
  );
}

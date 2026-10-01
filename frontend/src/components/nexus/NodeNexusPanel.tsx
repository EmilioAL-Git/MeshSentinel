import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type CSSProperties } from "react";
import {
  createNexusOperation,
  fetchGateways,
  fetchNexusKnownFlags,
  fetchNexusOperations,
  fetchNexusSettings,
  previewNexusOperation,
  type NexusKnownFlagOut,
  type NexusOperationOut,
  type NexusOperationPreviewOut,
  type NexusTargetKind,
} from "../../api/client";
import { toast } from "../shell/Toast";
import { t } from "../../tokens";
import { NexusCatalogBrowser } from "./NexusCatalogBrowser";
import { NexusCommandHint } from "./NexusCommandHint";
import { STATUS_COLORS, STATUS_LABELS } from "./NexusOperationsPanel";

const btn: CSSProperties = {
  background: "transparent",
  border: `1px solid ${t.border}`,
  color: t.text,
  borderRadius: 4,
  cursor: "pointer",
  fontSize: 11,
  padding: "0.1rem 0.5rem",
};

const input: CSSProperties = {
  background: t.bg,
  border: `1px solid ${t.border}`,
  color: t.text,
  borderRadius: 4,
  padding: "0.15rem 0.4rem",
  fontSize: 12,
};

/**
 * Cola de operaciones Nexus (ADR 0027 §4) ESCOPADA a este nodo — destino
 * fijo (-node <shortname>, el único direccionamiento dirigido soportado,
 * §0.2): quien abre esta pestaña ya eligió el nodo, no tiene sentido
 * volver a pedirlo. Reutiliza el mismo flujo previsualizar→confirmar de
 * `NexusOperationsPanel` (Ajustes → JenTastic-Nexus, sin destino fijo) sin
 * duplicar la lógica del backend: es el mismo endpoint con los mismos
 * parámetros, solo con `target_value` precargado y sin selector de tipo de
 * destino.
 */
export function NodeNexusPanel({
  nodeId,
  shortName,
  defaultGatewayId,
}: {
  nodeId: string;
  shortName: string;
  defaultGatewayId: string | null;
}) {
  const queryClient = useQueryClient();
  const gatewaysQuery = useQuery({ queryKey: ["gateways"], queryFn: () => fetchGateways() });
  const gateways = (gatewaysQuery.data ?? []).filter((g) => g.status === "connected");
  // Ajuste "direccionar por defecto" (ADR 0027 §13, id vs shortname): decide
  // con qué -kind/-value habla ESTE panel con SU nodo — nunca cambia lo que
  // el operador puede elegir en el formulario genérico de Ajustes, solo el
  // valor por defecto de esta pestaña, escopada a un único nodo.
  const settingsQuery = useQuery({ queryKey: ["nexus-settings"], queryFn: fetchNexusSettings });
  const addressingMode = settingsQuery.data?.addressing_mode ?? "shortname";
  const targetKind: NexusTargetKind = addressingMode === "device_id" ? "device" : "node";
  const targetValue = addressingMode === "device_id" ? nodeId : shortName;

  const [gatewayId, setGatewayId] = useState(defaultGatewayId ?? "");
  // `defaultGatewayId` llega a menudo DESPUÉS del primer render (enlaces del
  // nodo aún cargando): `useState` solo lo lee al montar, y el panel se
  // quedaba sin pasarela con «Leer estado» y «Preparar…» desactivados sin
  // explicación. Se adopta en cuanto aparece: la pasarela del nodo si está
  // conectada, la de los ajustes, o la única conectada.
  useEffect(() => {
    if (gatewayId) return;
    const connected = new Set(gateways.map((g) => g.gateway_id));
    const preferred = [defaultGatewayId, settingsQuery.data?.default_gateway_id].find(
      (id): id is string => !!id && connected.has(id),
    );
    if (preferred) setGatewayId(preferred);
    else if (gateways.length === 1) setGatewayId(gateways[0]!.gateway_id);
  }, [gatewayId, gateways, defaultGatewayId, settingsQuery.data]);
  const [command, setCommand] = useState("");
  const [argsInput, setArgsInput] = useState("");
  const [preview, setPreview] = useState<NexusOperationPreviewOut | null>(null);
  const [confirmText, setConfirmText] = useState("");

  // Historial compartido: alimenta tanto la sección de Seguridad (último
  // SECURITY confirmado) como el listado de abajo — una sola query con
  // polling de 3 s, en vez de duplicarla por sección. Empareja por
  // CUALQUIERA de los dos direccionamientos posibles (shortname/-node o
  // node_id/-device): el operador puede haber cambiado de ajuste desde la
  // última operación, el historial de este nodo no debe perder esas filas.
  const opsQuery = useQuery({
    queryKey: ["nexus-operations", "node", nodeId],
    queryFn: () => fetchNexusOperations(undefined, undefined, 200),
    refetchInterval: 3000,
  });
  const ops = (opsQuery.data ?? []).filter(
    (op) =>
      (op.target_kind === "node" && op.target_value === shortName) ||
      (op.target_kind === "device" && op.target_value === nodeId),
  );

  const args = argsInput.trim() ? argsInput.trim().split(/\s+/) : [];
  const body = {
    gateway_id: gatewayId,
    command: command.trim().toUpperCase(),
    args,
    target_kind: targetKind,
    target_value: targetValue,
  };
  const canBuild = gatewayId !== "" && command.trim() !== "";

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
      setArgsInput("");
      queryClient.invalidateQueries({ queryKey: ["nexus-operations"] });
    },
    onError: (err) =>
      toast(err instanceof Error ? err.message.replace(/^HTTP \d+: /, "") : "No se pudo añadir a la cola", {
        kind: "error",
      }),
  });

  const needsTypedConfirm = preview?.destructive ?? false;
  const canQueue = preview != null && (!needsTypedConfirm || confirmText.trim() === targetValue);

  // Precarga el formulario Y previsualiza al instante (si hay pasarela): antes
  // «Preparar activación» solo rellenaba unos campos más abajo y parecía que
  // «no hacía nada». Sigue sin enviar: falta «Añadir a la cola».
  const prefill = (cmd: string, argsStr: string) => {
    setCommand(cmd);
    setArgsInput(argsStr);
    setPreview(null);
    if (!gatewayId) {
      toast("Elige una pasarela en el formulario de abajo para previsualizar", { kind: "error" });
      return;
    }
    previewNexusOperation({
      ...body,
      command: cmd.trim().toUpperCase(),
      args: argsStr.trim() ? argsStr.trim().split(/\s+/) : [],
    })
      .then((data) => {
        setPreview(data);
        setConfirmText("");
        toast(`Preparado: ${data.text} — revisa abajo y pulsa «Añadir a la cola»`);
      })
      .catch((err) =>
        toast(err instanceof Error ? err.message.replace(/^HTTP \d+: /, "") : "No se pudo construir", { kind: "error" }),
      );
  };

  return (
    <div>
      {gatewayId === "" && (
        <div style={{ color: t.warn, fontSize: 11.5, marginBottom: 6 }}>
          Elige una pasarela (selector «Pasarela…» más abajo) para poder leer y enviar comandos a este nodo.
        </div>
      )}
      <NodeNexusSecurity ops={ops} gatewayId={gatewayId} targetKind={targetKind} targetValue={targetValue} onPrefill={prefill} />
      <div style={{ marginTop: 8 }}>
        <NodeNexusProfile ops={ops} gatewayId={gatewayId} targetKind={targetKind} targetValue={targetValue} onPrefill={prefill} />
      </div>
      <div style={{ marginTop: 8 }}>
        <NodeNexusFavorites nodeId={nodeId} ops={ops} gatewayId={gatewayId} targetKind={targetKind} targetValue={targetValue} onPrefill={prefill} />
      </div>
      <div style={{ marginTop: 8 }}>
        <NodeNexusZeroHop ops={ops} gatewayId={gatewayId} targetKind={targetKind} targetValue={targetValue} onPrefill={prefill} />
      </div>

      <p style={{ color: t.textFaint, fontSize: 11.5, margin: "0.8rem 0 0.6rem" }}>
        Comandos por texto al firmware JenTastic-Nexus de este nodo (
        <code>{targetKind === "device" ? "-device" : "-node"} {targetValue}</code>
        ), siempre con previsualización antes de añadir a la cola.
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
        <select style={input} value={gatewayId} onChange={(e) => { setGatewayId(e.target.value); setPreview(null); }}>
          <option value="">Pasarela…</option>
          {gateways.map((g) => (
            <option key={g.gateway_id} value={g.gateway_id}>{g.name || g.gateway_id}</option>
          ))}
        </select>
        <input
          style={{ ...input, width: 120, fontFamily: t.fontMono }}
          placeholder="COMANDO"
          value={command}
          onChange={(e) => { setCommand(e.target.value); setPreview(null); }}
        />
        <input
          style={{ ...input, width: 150, fontFamily: t.fontMono }}
          placeholder="argumentos"
          value={argsInput}
          onChange={(e) => { setArgsInput(e.target.value); setPreview(null); }}
        />
        <button style={btn} disabled={!canBuild || previewMutation.isPending} onClick={() => previewMutation.mutate()}>
          Previsualizar
        </button>
      </div>
      <NexusCommandHint command={command} />
      <div style={{ marginTop: 6 }}>
        <NexusCatalogBrowser onSelect={(name, nextArgs) => { setCommand(name); setArgsInput(nextArgs.join(" ")); setPreview(null); }} />
      </div>

      {preview && (
        <div style={{ marginTop: 8, padding: "0.5rem 0.6rem", background: t.surface2, border: `1px solid ${t.borderSubtle}`, borderRadius: 6 }}>
          <div style={{ fontFamily: t.fontMono, fontSize: 12.5 }}>{preview.text}</div>
          <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
            {preview.destructive && <span style={{ color: t.crit, fontSize: 10.5 }}>⚠ destructivo</span>}
            {preview.requires_save && <span style={{ color: t.warn, fontSize: 10.5 }}>requiere SAVE</span>}
            {preview.busy_seconds > 0 && (
              <span style={{ color: t.textFaint, fontSize: 10.5 }}>ocupa el nodo {preview.busy_seconds}s</span>
            )}
          </div>
          {needsTypedConfirm && (
            <div style={{ marginTop: 6 }}>
              <div style={{ color: t.textFaint, fontSize: 10.5 }}>
                Comando destructivo — escribe <strong style={{ fontFamily: t.fontMono }}>{targetValue}</strong> para confirmar
              </div>
              <input
                style={{ ...input, display: "block", marginTop: 4, width: 160 }}
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
              />
            </div>
          )}
          <button
            style={{ ...btn, marginTop: 8, borderColor: t.accent, color: t.accent }}
            disabled={!canQueue || createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            Añadir a la cola
          </button>
        </div>
      )}

      <NodeNexusHistory ops={ops} />
    </div>
  );
}

const SECURITY_BIT_LABEL: Record<string, string> = {
  req_sig: "Requiere firma",
  allow_dm: "Acepta DM",
  silent: "Registro silencioso",
  fav_nx: "Auto-favorito (Nexus)",
  fav_tr: "Auto-favorito (confianza)",
  bypass_rp: "Salta protección de repetición",
  bypass_rp_extra: "Anti-repetición (ocupación)",
};

/**
 * Punto 3 del encargo (ADR 0027, `docs/design/nexus-control.md`): leer
 * `SECURITY` y mostrar el bitmask, avisando si `ALLOW_DM` está OFF. Nunca
 * envía nada por sí sola salvo la propia lectura (consulta, no muta) — la
 * activación de `ALLOW_DM` solo PRECARGA el formulario genérico de abajo,
 * el operador sigue teniendo que previsualizar y añadir a la cola como cualquier
 * otro comando (mismo criterio de "nunca automático" del resto del
 * módulo). El estado mostrado es el de la última lectura CONFIRMADA — sin
 * SET remoto, MeshSentinel no puede releer la NodeDB para verificarlo por
 * su cuenta, exactamente igual que M4.1/M4.2.
 */
function NodeNexusSecurity({
  ops,
  gatewayId,
  targetKind,
  targetValue,
  onPrefill,
}: {
  ops: NexusOperationOut[];
  gatewayId: string;
  targetKind: NexusTargetKind;
  targetValue: string;
  onPrefill: (command: string, args: string) => void;
}) {
  const queryClient = useQueryClient();
  const latest = ops.find(
    (op) => op.command_name === "SECURITY" && op.status === "confirmed" && op.response_kind === "structured",
  );
  const pending = ops.find((op) => op.command_name === "SECURITY" && (op.status === "pending" || op.status === "sent"));

  const readMutation = useMutation({
    mutationFn: async () => {
      if (!gatewayId) throw new Error("Elige antes una pasarela en el formulario de abajo");
      const opBody = {
        gateway_id: gatewayId,
        command: "SECURITY",
        args: [],
        target_kind: targetKind,
        target_value: targetValue,
      };
      return createNexusOperation(opBody);
    },
    onSuccess: () => {
      toast("Leyendo SECURITY…");
      queryClient.invalidateQueries({ queryKey: ["nexus-operations"] });
    },
    onError: (err) => toast(err instanceof Error ? err.message : "No se pudo leer", { kind: "error" }),
  });

  const bits = latest?.response_data ?? null;
  const allowDmValue = bits?.["allow_dm"] as string | undefined;
  const allowDmOff = allowDmValue === "off";

  return (
    <div style={{ padding: "0.5rem 0.6rem", background: t.surface2, border: `1px solid ${t.borderSubtle}`, borderRadius: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ color: t.textDim, fontSize: 11.5, fontWeight: 600, flex: 1 }}>SEGURIDAD (SECURITY)</span>
        <button
          style={btn}
          disabled={readMutation.isPending || pending != null || !gatewayId}
          title={!gatewayId ? "Elige antes una pasarela en el formulario de abajo" : undefined}
          onClick={() => readMutation.mutate()}
        >
          {pending ? "Leyendo…" : "Leer estado"}
        </button>
      </div>

      {!bits && <div style={{ color: t.textFaint, fontSize: 11.5, marginTop: 6 }}>Sin lectura confirmada todavía.</div>}

      {bits && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 6 }}>
          {Object.entries(bits)
            .filter(([key, v]) => key !== "marker" && typeof v === "string")
            .map(([key, value]) => (
              <span
                key={key}
                title={key}
                style={{
                  fontSize: 10.5,
                  padding: "0.1rem 0.4rem",
                  borderRadius: 3,
                  border: `1px solid ${value === "on" ? t.ok : t.borderSubtle}`,
                  color: value === "on" ? t.ok : t.textFaint,
                }}
              >
                {SECURITY_BIT_LABEL[key] ?? key} · {String(value)}
              </span>
            ))}
        </div>
      )}

      {allowDmOff && (
        <div style={{ marginTop: 8, padding: "0.4rem 0.5rem", background: t.bg, border: `1px solid ${t.warn}`, borderRadius: 5 }}>
          <div style={{ color: t.warn, fontSize: 11 }}>
            ⚠ ALLOW_DM desactivado — este nodo no aceptará mensajes directos hasta activarlo.
          </div>
          <button
            style={{ ...btn, marginTop: 6 }}
            onClick={() => onPrefill("SECURITY", "ALLOW_DM on")}
            title="Precarga el formulario de abajo — sigues teniendo que previsualizar y añadir a la cola tú"
          >
            Preparar activación (+ recuerda SAVE después)
          </button>
        </div>
      )}
    </div>
  );
}

// Campos de SETCONFIG confirmados por captura real (2026-09-28, ver
// catalog.py): "JT SETCONFIG: NI|TEL_D|TEL_E|TEL_P|POS|SMART|FIXED|GPS
// <val> | LOC lat,lon" — un valor por campo, LOC en forma especial
// "lat,lon" sin espacio. `configKey` es la clave que devuelve parse_config
// (parsers.py); `setField` es el nombre real que espera SETCONFIG.
const PROFILE_FIELDS: { configKey: string; setField: string; label: string; kind: "seconds" | "bool" }[] = [
  { configKey: "ni_seconds", setField: "NI", label: "Intervalo NodeInfo", kind: "seconds" },
  { configKey: "tel_d_seconds", setField: "TEL_D", label: "Telemetría dispositivo", kind: "seconds" },
  { configKey: "tel_e_seconds", setField: "TEL_E", label: "Telemetría entorno", kind: "seconds" },
  { configKey: "tel_p_seconds", setField: "TEL_P", label: "Telemetría potencia", kind: "seconds" },
  { configKey: "pos_seconds", setField: "POS", label: "Intervalo posición", kind: "seconds" },
  { configKey: "smart", setField: "SMART", label: "Posición inteligente", kind: "bool" },
  { configKey: "fixed", setField: "FIXED", label: "Posición fija", kind: "bool" },
  { configKey: "gps", setField: "GPS", label: "GPS", kind: "bool" },
];

/**
 * Punto 4 del encargo (ADR 0027, `docs/design/nexus-control.md` §Punto 4):
 * plantilla de perfil de nodo sobre `CONFIG`/`SETCONFIG`. Alcance real,
 * recortado por captura de campo (2026-09-28): el "rol" y el LoRa manual
 * (SF/BW/CR/Freq) que pedía el encargo original NO son editables desde
 * aquí — `SETROLE` y `SETLORA` devolvieron los dos "JT: Unknown command"
 * contra el nodo real (build privada, más comandos que la pública — si ni
 * siquiera ahí existen, no se puede ofrecer un botón que los use). Solo se
 * ofrecen los 8 campos de `SETCONFIG` que el propio firmware confirmó en
 * su mensaje de uso. Mismo criterio que Seguridad: nunca envía el cambio
 * por sí solo, solo PRECARGA el formulario genérico de abajo.
 */
function NodeNexusProfile({
  ops,
  gatewayId,
  targetKind,
  targetValue,
  onPrefill,
}: {
  ops: NexusOperationOut[];
  gatewayId: string;
  targetKind: NexusTargetKind;
  targetValue: string;
  onPrefill: (command: string, args: string) => void;
}) {
  const queryClient = useQueryClient();
  const latest = ops.find(
    (op) => op.command_name === "CONFIG" && op.status === "confirmed" && op.response_kind === "structured",
  );
  const pending = ops.find((op) => op.command_name === "CONFIG" && (op.status === "pending" || op.status === "sent"));
  const cfg = latest?.response_data ?? null;

  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");

  const readMutation = useMutation({
    mutationFn: async () => {
      if (!gatewayId) throw new Error("Elige antes una pasarela en el formulario de abajo");
      return createNexusOperation({
        gateway_id: gatewayId,
        command: "CONFIG",
        args: [],
        target_kind: targetKind,
        target_value: targetValue,
      });
    },
    onSuccess: () => {
      toast("Leyendo CONFIG…");
      queryClient.invalidateQueries({ queryKey: ["nexus-operations"] });
    },
    onError: (err) => toast(err instanceof Error ? err.message : "No se pudo leer", { kind: "error" }),
  });

  return (
    <div style={{ padding: "0.5rem 0.6rem", background: t.surface2, border: `1px solid ${t.borderSubtle}`, borderRadius: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ color: t.textDim, fontSize: 11.5, fontWeight: 600, flex: 1 }}>PERFIL (CONFIG)</span>
        <button
          style={btn}
          disabled={readMutation.isPending || pending != null || !gatewayId}
          title={!gatewayId ? "Elige antes una pasarela en el formulario de abajo" : undefined}
          onClick={() => readMutation.mutate()}
        >
          {pending ? "Leyendo…" : "Leer configuración"}
        </button>
      </div>

      {!cfg && <div style={{ color: t.textFaint, fontSize: 11.5, marginTop: 6 }}>Sin lectura confirmada todavía.</div>}

      {cfg && (
        <>
          <div style={{ color: t.textFaint, fontSize: 10.5, marginTop: 6 }}>
            Rol: <span style={{ fontFamily: t.fontMono }}>{String(cfg["role"] ?? "—")}</span> (solo lectura — sin comando
            confirmado para cambiarlo desde Nexus en este firmware)
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 6 }}>
            {PROFILE_FIELDS.map((f) => {
              const current = cfg[f.configKey];
              const draft = drafts[f.setField] ?? "";
              return (
                <div key={f.setField} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5 }}>
                  <span style={{ width: 150, color: t.textDim }}>{f.label}</span>
                  <span style={{ width: 60, fontFamily: t.fontMono, color: t.textFaint }}>{String(current ?? "—")}</span>
                  {f.kind === "bool" ? (
                    <select
                      style={{ ...input, width: 70 }}
                      value={draft}
                      onChange={(e) => setDrafts((d) => ({ ...d, [f.setField]: e.target.value }))}
                    >
                      <option value="">…</option>
                      <option value="on">ON</option>
                      <option value="off">OFF</option>
                    </select>
                  ) : (
                    <input
                      style={{ ...input, width: 90 }}
                      placeholder="nuevo valor"
                      value={draft}
                      onChange={(e) => setDrafts((d) => ({ ...d, [f.setField]: e.target.value }))}
                    />
                  )}
                  <button
                    style={btn}
                    disabled={!draft.trim()}
                    onClick={() => onPrefill("SETCONFIG", `${f.setField} ${draft.trim()}`)}
                  >
                    Preparar cambio
                  </button>
                </div>
              );
            })}
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5 }}>
              <span style={{ width: 150, color: t.textDim }}>Ubicación fija (LOC)</span>
              <span style={{ width: 60, fontFamily: t.fontMono, color: t.textFaint, fontSize: 10 }}>
                {String(cfg["loc"] ?? "—")}
              </span>
              <input style={{ ...input, width: 70 }} placeholder="lat" value={lat} onChange={(e) => setLat(e.target.value)} />
              <input style={{ ...input, width: 70 }} placeholder="lon" value={lon} onChange={(e) => setLon(e.target.value)} />
              <button
                style={btn}
                disabled={!lat.trim() || !lon.trim()}
                onClick={() => onPrefill("SETCONFIG", `LOC ${lat.trim()},${lon.trim()}`)}
              >
                Preparar cambio
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/**
 * Favoritos/ignorados propios de JenTastic-Nexus — pedido explícito del
 * usuario ("¿tienes registro de favoritos e ignorados con Nexus? ¿Y con
 * Nexus?"), confirmado por captura real que SÍ es "solicitable"
 * (catálogo NodeDB: `FAVS`/`IGNORED` consulta, `FAV`/`UNFAV` mutan).
 * SIN relación con los favoritos/ignorados remotos nativos (M4.1/M4.2,
 * AdminMessage) — mecanismo totalmente distinto, lista distinta, botón
 * distinto. Solo `FAV`/`UNFAV` tienen atajo aquí: `IGNORE`/`UNIGNORE` no
 * se han probado contra hardware todavía (parsers.py), así que la lista
 * de ignorados es de solo lectura — añadir/quitar sigue disponible a
 * mano desde el catálogo completo, sin atajo dedicado hasta confirmarlo.
 */
function NodeNexusFavorites({
  nodeId,
  ops,
  gatewayId,
  targetKind,
  targetValue,
  onPrefill,
}: {
  nodeId: string;
  ops: NexusOperationOut[];
  gatewayId: string;
  targetKind: NexusTargetKind;
  targetValue: string;
  onPrefill: (command: string, args: string) => void;
}) {
  const queryClient = useQueryClient();
  const [newFavId, setNewFavId] = useState("");
  const [newIgnoredId, setNewIgnoredId] = useState("");
  const [newNignId, setNewNignId] = useState("");

  // Listas CONOCIDAS: lo que este nodo ha confirmado (FAV/UNFAV/IGNORE/
  // UNIGNORE, también por difusión desde la consola) y sus lecturas
  // FAVS/IGNORED — el backend las acumula, ya no dependen de la última
  // lectura de esta pestaña.
  const knownQuery = useQuery({
    queryKey: ["nexus-flags", nodeId],
    queryFn: () => fetchNexusKnownFlags(nodeId),
    refetchInterval: 5000,
  });
  const knownFlags = knownQuery.data ?? [];

  const latestFavs = ops.find(
    (op) => op.command_name === "FAVS" && op.status === "confirmed" && op.response_kind === "structured",
  );
  const latestIgnored = ops.find(
    (op) => op.command_name === "IGNORED" && op.status === "confirmed" && op.response_kind === "structured",
  );
  const pendingFavs = ops.find((op) => op.command_name === "FAVS" && (op.status === "pending" || op.status === "sent"));
  const pendingIgnored = ops.find(
    (op) => op.command_name === "IGNORED" && (op.status === "pending" || op.status === "sent"),
  );

  const readMutation = useMutation({
    mutationFn: async (command: "FAVS" | "IGNORED" | "NIGN") => {
      if (!gatewayId) throw new Error("Elige antes una pasarela en el formulario de abajo");
      return createNexusOperation({
        gateway_id: gatewayId, command, args: command === "NIGN" ? ["LIST"] : [], target_kind: targetKind, target_value: targetValue,
      });
    },
    onSuccess: (_data, command) => {
      toast(`Leyendo ${command}…`);
      queryClient.invalidateQueries({ queryKey: ["nexus-operations"] });
    },
    onError: (err) => toast(err instanceof Error ? err.message : "No se pudo leer", { kind: "error" }),
  });

  const toEntry = (f: NexusKnownFlagOut) => ({ node_id: f.subject_node_id, label: f.subject_label });
  const favEntries = latestFavs || knownFlags.some((f) => f.flag_type === "favorite")
    ? knownFlags.filter((f) => f.flag_type === "favorite").map(toEntry)
    : null;
  const nignEntries = knownFlags.some((f) => f.flag_type === "nign")
    ? knownFlags.filter((f) => f.flag_type === "nign").map(toEntry)
    : null;
  const ignoredEntries = latestIgnored || knownFlags.some((f) => f.flag_type === "ignored")
    ? knownFlags.filter((f) => f.flag_type === "ignored").map(toEntry)
    : null;

  return (
    <div style={{ padding: "0.5rem 0.6rem", background: t.surface2, border: `1px solid ${t.borderSubtle}`, borderRadius: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ color: t.textDim, fontSize: 11.5, fontWeight: 600, flex: 1 }}>FAVORITOS / IGNORADOS (Nexus)</span>
      </div>
      <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
        <button
          style={btn}
          disabled={readMutation.isPending || pendingFavs != null || !gatewayId}
          onClick={() => readMutation.mutate("FAVS")}
        >
          {pendingFavs ? "Leyendo…" : "Leer favoritos"}
        </button>
        <button
          style={btn}
          disabled={readMutation.isPending || pendingIgnored != null || !gatewayId}
          onClick={() => readMutation.mutate("IGNORED")}
        >
          {pendingIgnored ? "Leyendo…" : "Leer ignorados"}
        </button>
        <button
          style={btn}
          title="NIGN LIST: lista de ignorados persistente (vault), sobrevive a reinicios"
          disabled={readMutation.isPending || !gatewayId}
          onClick={() => readMutation.mutate("NIGN")}
        >
          Leer NIGN
        </button>
      </div>

      {favEntries && (
        <div style={{ marginTop: 8 }}>
          <div style={{ color: t.textFaint, fontSize: 10.5 }}>FAVORITOS ({favEntries.length})</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2, marginTop: 3, maxHeight: 140, overflowY: "auto" }}>
            {favEntries.map((e) => (
              <div key={e.node_id} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5 }}>
                <span className="mono" style={{ flex: 1 }}>{e.label}</span>
                <button style={btn} onClick={() => onPrefill("UNFAV", e.node_id)}>Quitar</button>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
            <input
              style={{ ...input, width: 110, fontFamily: t.fontMono }}
              placeholder="!id"
              value={newFavId}
              onChange={(e) => setNewFavId(e.target.value)}
            />
            <button style={btn} disabled={!newFavId.trim()} onClick={() => onPrefill("FAV", newFavId.trim())}>
              Añadir
            </button>
          </div>
        </div>
      )}

      {ignoredEntries && (
        <div style={{ marginTop: 8 }}>
          <div style={{ color: t.textFaint, fontSize: 10.5 }}>IGNORADOS ({ignoredEntries.length})</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2, marginTop: 3, maxHeight: 140, overflowY: "auto" }}>
            {ignoredEntries.length === 0 && <div style={{ color: t.textFaint, fontSize: 11.5 }}>Ninguno.</div>}
            {ignoredEntries.map((e) => (
              <div key={e.node_id} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5 }}>
                <span className="mono" style={{ flex: 1 }}>{e.label}</span>
                <button style={btn} onClick={() => onPrefill("UNIGNORE", e.node_id)}>Quitar</button>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
            <input
              style={{ ...input, width: 110, fontFamily: t.fontMono }}
              placeholder="!id"
              value={newIgnoredId}
              onChange={(e) => setNewIgnoredId(e.target.value)}
            />
            <button style={btn} disabled={!newIgnoredId.trim()} onClick={() => onPrefill("IGNORE", newIgnoredId.trim())}>
              Añadir
            </button>
          </div>
        </div>
      )}

      {(nignEntries || newNignId) && (
        <div style={{ marginTop: 8 }}>
          <div style={{ color: t.textFaint, fontSize: 10.5 }}>
            IGNORADOS PERSISTENTES — NIGN ({nignEntries?.length ?? 0}) · sobreviven a reinicios, hasta 64
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2, marginTop: 3, maxHeight: 140, overflowY: "auto" }}>
            {(nignEntries ?? []).length === 0 && <div style={{ color: t.textFaint, fontSize: 11.5 }}>Ninguno.</div>}
            {(nignEntries ?? []).map((e) => (
              <div key={e.node_id} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5 }}>
                <span className="mono" style={{ flex: 1 }}>{e.label}</span>
                <button style={btn} onClick={() => onPrefill("NIGN", `REM ${e.node_id}`)}>Quitar</button>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
            <input
              style={{ ...input, width: 110, fontFamily: t.fontMono }}
              placeholder="!id"
              value={newNignId}
              onChange={(e) => setNewNignId(e.target.value)}
            />
            <button style={btn} disabled={!newNignId.trim()} onClick={() => onPrefill("NIGN", `ADD ${newNignId.trim()}`)}>
              Añadir
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Zero Hop (categoría Firewall del catálogo) — pedido explícito del
 * usuario: destacarlo igual que Favoritos/Ignorados. `ZH ADD`/`ZH DEL`
 * esperan solo los 2 últimos hex del id (`addressing.zero_hop_suffix`,
 * confirmado real y por el usuario: "el ZH es sólo con los dos últimos
 * dígitos del ID") — `build_command` trunca automáticamente lo que se
 * escriba aquí (un `!id` completo o ya solo 2 hex, da igual), así que el
 * panel no duplica esa lógica en el cliente.
 */
function NodeNexusZeroHop({
  ops,
  gatewayId,
  targetKind,
  targetValue,
  onPrefill,
}: {
  ops: NexusOperationOut[];
  gatewayId: string;
  targetKind: NexusTargetKind;
  targetValue: string;
  onPrefill: (command: string, args: string) => void;
}) {
  const queryClient = useQueryClient();
  const [newZhId, setNewZhId] = useState("");

  const latest = ops.find(
    (op) => op.command_name === "ZH" && op.args[0] === "LIST" && op.status === "confirmed" && op.response_kind === "structured",
  );
  const pending = ops.find((op) => op.command_name === "ZH" && op.args[0] === "LIST" && (op.status === "pending" || op.status === "sent"));

  const readMutation = useMutation({
    mutationFn: async () => {
      if (!gatewayId) throw new Error("Elige antes una pasarela en el formulario de abajo");
      return createNexusOperation({
        gateway_id: gatewayId, command: "ZH", args: ["LIST"], target_kind: targetKind, target_value: targetValue,
      });
    },
    onSuccess: () => {
      toast("Leyendo ZH…");
      queryClient.invalidateQueries({ queryKey: ["nexus-operations"] });
    },
    onError: (err) => toast(err instanceof Error ? err.message : "No se pudo leer", { kind: "error" }),
  });

  const entries = (latest?.response_data?.["entries"] as { zh_id: string; short_name: string; extra: string }[] | undefined) ?? null;

  return (
    <div style={{ padding: "0.5rem 0.6rem", background: t.surface2, border: `1px solid ${t.borderSubtle}`, borderRadius: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ color: t.textDim, fontSize: 11.5, fontWeight: 600, flex: 1 }}>ZERO HOP (ZH)</span>
        <button
          style={btn}
          disabled={readMutation.isPending || pending != null || !gatewayId}
          title={!gatewayId ? "Elige antes una pasarela en el formulario de abajo" : undefined}
          onClick={() => readMutation.mutate()}
        >
          {pending ? "Leyendo…" : "Leer lista"}
        </button>
      </div>

      {!entries && <div style={{ color: t.textFaint, fontSize: 11.5, marginTop: 6 }}>Sin lectura confirmada todavía.</div>}

      {entries && (
        <>
          <div style={{ display: "flex", flexDirection: "column", gap: 2, marginTop: 6, maxHeight: 140, overflowY: "auto" }}>
            {entries.length === 0 && <div style={{ color: t.textFaint, fontSize: 11.5 }}>Ninguno.</div>}
            {entries.map((e) => (
              <div key={e.zh_id} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5 }}>
                <span className="mono" style={{ flex: 1 }}>
                  [{e.zh_id}] {e.short_name} <span style={{ color: t.textFaint }}>{e.extra}</span>
                </span>
                <button style={btn} onClick={() => onPrefill("ZH", `DEL ${e.zh_id}`)}>Quitar</button>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
            <input
              style={{ ...input, width: 110, fontFamily: t.fontMono }}
              placeholder="!id o 2 hex"
              value={newZhId}
              onChange={(e) => setNewZhId(e.target.value)}
            />
            <button style={btn} disabled={!newZhId.trim()} onClick={() => onPrefill("ZH", `ADD ${newZhId.trim()}`)}>
              Añadir
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function NodeNexusHistory({ ops }: { ops: NexusOperationOut[] }) {
  if (ops.length === 0) {
    return <div style={{ color: t.textFaint, fontSize: 12, marginTop: 10 }}>Sin operaciones Nexus para este nodo.</div>;
  }
  return (
    <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 4 }}>
      {ops.slice(0, 10).map((op) => (
        <NodeNexusOpRow key={op.id} op={op} />
      ))}
    </div>
  );
}

function NodeNexusOpRow({ op }: { op: NexusOperationOut }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div
      style={{
        padding: "0.35rem 0.55rem",
        fontSize: 12,
        background: t.surface2,
        border: `1px solid ${t.borderSubtle}`,
        borderRadius: 5,
        cursor: op.response_text ? "pointer" : undefined,
      }}
      onClick={() => op.response_text && setExpanded((v) => !v)}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: "0.45rem" }}>
        <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: t.fontMono }}>
          {op.text}
        </span>
        <span style={{ color: STATUS_COLORS[op.status], fontSize: 10.5 }}>{STATUS_LABELS[op.status]}</span>
      </div>
      {expanded && op.response_text && (
        <pre style={{ fontFamily: t.fontMono, whiteSpace: "pre-wrap", margin: "6px 0 0", fontSize: 11, color: t.textDim }}>
          {op.response_text}
        </pre>
      )}
    </div>
  );
}

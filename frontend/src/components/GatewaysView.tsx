import {
  NetFields, VirtualNodeFields, DEFAULT_PORT, emptyNet, emptyVn, isNetType, netParams, netReady,
  vnFromParams, vnValid, withVn, type NetState, type VnState,
} from "./gateways/NetTransport";
import { useAuth } from "../context/AuthContext";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  configureGateway,
  connectGateway,
  reorderGateways,
  resyncGateway,
  setGatewayPrimary,
  setGatewayReceiveOnly,
  createGateway,
  deleteGateway,
  disconnectGateway,
  discoverDevices,
  fetchGateways,
  fetchGatewayStats,
  fetchLauncherDevices,
  importGateway,
  testGatewayConnection,
  updateGateway,
  type DeviceOut,
  type GatewayOut,
  type GatewayStatsOut,
  type GatewayStatus,
  type TestConnectionResultOut,
} from "../api/client";
import { relativeTime } from "../time";

/**
 * Enlaces (identidad v0.8): las pasarelas son módulos de un rack — un panel
 * por enlace con luz de estado, telemetría de cobertura M6.2 y controles
 * inline. "+ Añadir enlace" (ADR 0028) tiene dos caminos: crear un
 * contenedor nuevo (gateway-launcher lo crea/destruye bajo demanda, sin
 * tocar docker-compose.yml) o registrar un proceso externo que el operador
 * ya arranca por su cuenta (nativo, `.env`, otro host). Ya no existe la
 * piscina estática de repuestos (M6.3, retirada).
 */

/** slug apto como gateway_id a partir del nombre elegido por el operador. */
function slugify(name: string): string {
  const base = name
    .trim()
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return base ? `gw-${base}` : "";
}

const STATUS_COLOR: Record<string, string> = {
  connected: "var(--ok)",
  connecting: "var(--warn)",
  reconnecting: "var(--warn)",
  disconnected: "var(--crit)",
  error: "var(--crit)",
  unassigned: "var(--text-faint)",
};

const STATUS_LABEL: Record<string, string> = {
  connected: "Conectado",
  connecting: "Conectando…",
  reconnecting: "Reconectando…",
  disconnected: "Desconectado",
  error: "Error",
  unassigned: "Sin conexión",
};

function StatusLight({ status }: { status: GatewayStatus | string }) {
  const color = STATUS_COLOR[status] ?? "var(--crit)";
  const pulse = status === "connected" || status === "connecting" || status === "reconnecting";
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color }}>
      <span className={pulse ? "noc-pulse" : undefined} style={{ fontSize: 9 }}>●</span>
      <span style={{ fontSize: 12 }}>{STATUS_LABEL[status] ?? status}</span>
    </span>
  );
}

const TRANSPORT_LABEL: Record<string, string> = {
  usb: "USB",
  serial: "USB",
  tcp: "TCP",
  http: "HTTP",
  mqtt: "MQTT",
  simulated: "SIM",
  idle: "Inactivo",
};

/** Par clave/valor en mono, la unidad de lectura de los módulos del rack. */
function Field({ k, v, title, color }: { k: string; v: React.ReactNode; title?: string; color?: string }) {
  return (
    <div title={title} style={{ minWidth: 0 }}>
      <div className="microlabel">{k}</div>
      <div className="mono" style={{ fontSize: 12, color: color ?? "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {v}
      </div>
    </div>
  );
}

/** Enlace = el nodo conectado responde (decide si la pasarela está caída);
 *  RX/TX LoRa = hay tráfico de radio (silencio no es avería). */
function ActivitySignals({ gateway, lastHeardFallback, spaced }: { gateway: GatewayOut; lastHeardFallback: string | null; spaced: boolean }) {
  const resp = gateway.last_device_response_at;
  const ageS = resp ? (Date.now() - new Date(resp).getTime()) / 1000 : null;
  const connected = gateway.status === "connected";
  // El latido llega cada 30 s y sondea justo antes: >2 min sin respuesta = enlace colgado
  const linkColor = !connected ? "var(--text-dim)" : ageS === null ? "var(--text-dim)" : ageS > 120 ? "var(--crit)" : "var(--ok)";
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))", gap: "0.6rem", marginBottom: spaced ? "0.75rem" : 0 }}>
      <Field k="Enlace" v={connected ? relativeTime(resp) : "—"} color={linkColor} title="Última respuesta real del nodo conectado por USB/TCP. Si envejece con la pasarela 'conectada', el enlace está colgado." />
      <Field k="RX LoRa" v={relativeTime(gateway.last_lora_rx_at ?? lastHeardFallback)} title="Último paquete de otro nodo recibido por radio. Silencio = sin tráfico, no pasarela caída." />
      <Field k="TX LoRa" v={relativeTime(gateway.last_lora_tx_at)} title="Última transmisión ordenada a la malla (comandos, administración, texto)." />
    </div>
  );
}

// ── Asistente: crear un contenedor nuevo (ADR 0028), o registrar un proceso
// externo que el operador ya arranca por su cuenta ──────────────────────────

/** Paso "Crear un contenedor nuevo": el lanzador lo crea ya con el
 * transporte definitivo, sin el baile idle→reconectar de los repuestos
 * M6.3 (retirados) — una única llamada a POST /gateways. */
function CreateContainerStep({ onCancel, onCreated }: { onCancel: () => void; onCreated: () => void }) {
  const queryClient = useQueryClient();
  const [transportType, setTransportType] = useState<"usb" | "tcp" | "http" | "mqtt" | "simulated">("simulated");
  const [devices, setDevices] = useState<DeviceOut[] | null>(null);
  const [selectedPort, setSelectedPort] = useState("");
  const [net, setNet] = useState<NetState>(emptyNet());
  const [vn, setVn] = useState<VnState>(emptyVn());
  const [name, setName] = useState("");
  const [gatewayId, setGatewayId] = useState("");
  const [idEdited, setIdEdited] = useState(false);

  const connectionParams = (): Record<string, unknown> => {
    let base: Record<string, unknown> = {};
    if (transportType === "usb") base = selectedPort ? { device: selectedPort } : {};
    else if (isNetType(transportType)) base = netParams(transportType, net);
    return withVn(base, transportType, vn);
  };

  const discover = useMutation({
    mutationFn: () => fetchLauncherDevices(),
    onSuccess: (found) => setDevices(found),
  });

  const create = useMutation({
    mutationFn: () =>
      createGateway({
        gateway_id: gatewayId,
        name,
        transport_type: transportType,
        connection_params: connectionParams(),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["gateways"] });
      onCreated();
    },
  });

  const paramsReady = (isNetType(transportType) ? netReady(transportType, net) : true) && vnValid(vn);
  const idValid = /^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$/.test(gatewayId);

  return (
    <div className="panel-body">
      <p style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 0 }}>
        gateway-launcher crea un contenedor nuevo y lo conecta directamente con este transporte — no
        hace falta reconstruir ni tocar docker-compose.yml.
      </p>

      <div style={{ marginBottom: "0.8rem" }}>
        <span className="seg">
          {(["simulated", "usb", "tcp", "http", "mqtt"] as const).map((tt) => (
            <button
              key={tt}
              className={transportType === tt ? "on" : undefined}
              onClick={() => {
                setTransportType(tt);
                setDevices(null);
                if (isNetType(tt)) setNet((prev) => ({ ...prev, port: DEFAULT_PORT[tt] }));
              }}
            >
              {TRANSPORT_LABEL[tt]}
            </button>
          ))}
        </span>
      </div>

      {isNetType(transportType) && <NetFields type={transportType} net={net} onChange={setNet} />}
      {transportType !== "mqtt" && transportType !== "simulated" && <VirtualNodeFields vn={vn} onChange={setVn} />}

      {transportType === "usb" && (
        <div style={{ marginBottom: "0.8rem" }}>
          <button className="btn" disabled={discover.isPending} onClick={() => discover.mutate()}>
            {discover.isPending ? "Buscando…" : "⌕ Buscar dispositivos del host"}
          </button>
          {discover.isError && <p style={{ color: "var(--crit)", fontSize: 12 }}>{String(discover.error)}</p>}
          {devices != null && devices.length === 0 && (
            <p style={{ color: "var(--text-dim)", fontSize: 12 }}>
              Sin dispositivos detectados en el host de gateway-launcher.
            </p>
          )}
          {devices != null && devices.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem", marginTop: "0.5rem" }}>
              {devices.map((d) => (
                <label
                  key={d.port}
                  style={{
                    display: "flex", gap: "0.6rem", alignItems: "center", cursor: "pointer", fontSize: 12,
                    border: "1px solid " + (selectedPort === d.port ? "var(--accent)" : "var(--border)"),
                    borderRadius: 3, padding: "0.4rem 0.6rem",
                    background: selectedPort === d.port ? "var(--accent-tint)" : "transparent",
                  }}
                >
                  <input
                    type="radio"
                    name="device"
                    checked={selectedPort === d.port}
                    onChange={() => setSelectedPort(d.port)}
                  />
                  <span className="mono">{d.port}</span>
                  <span style={{ color: "var(--text-dim)" }}>{d.description ?? "—"}</span>
                  {d.vid && d.pid && <span style={{ color: "var(--text-faint)" }}>VID:PID {d.vid}:{d.pid}</span>}
                  {d.serial_number && <span style={{ color: "var(--text-faint)" }}>S/N {d.serial_number}</span>}
                </label>
              ))}
            </div>
          )}
          <p style={{ color: "var(--text-faint)", fontSize: 11 }}>
            Vacío = autodetección al arrancar el contenedor. Solo funciona si Docker puede ver
            dispositivos USB del host (no en Docker Desktop/macOS).
          </p>
        </div>
      )}

      <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", alignItems: "flex-end" }}>
        <label style={{ fontSize: 12 }}>
          Nombre{" "}
          <input
            className="input"
            style={{ minWidth: 200 }}
            placeholder="p. ej. Casa, Repetidor Norte…"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              if (!idEdited) setGatewayId(slugify(e.target.value));
            }}
          />
        </label>
        <label style={{ fontSize: 12 }}>
          gateway_id{" "}
          <input
            className="input mono"
            style={{ width: 160 }}
            value={gatewayId}
            onChange={(e) => { setGatewayId(e.target.value); setIdEdited(true); }}
          />
        </label>
        <button
          className="btn primary"
          disabled={!name.trim() || !idValid || !paramsReady || create.isPending}
          onClick={() => create.mutate()}
          title={!idValid ? "gateway_id: solo alfanumérico, '-', '_', '.'" : undefined}
        >
          {create.isPending ? "Creando…" : "Crear pasarela"}
        </button>
        <button className="btn ghost" onClick={onCancel}>✕ Cancelar</button>
      </div>
      {create.isError && <p style={{ color: "var(--crit)", fontSize: 12 }}>{String(create.error)}</p>}
    </div>
  );
}

/** Paso "Registrar externo": pre-registro de un proceso que el operador ya
 * arranca por su cuenta (nativo, `.env`, otro host) — gateway-launcher no
 * interviene. Mismo asistente Buscar→Probar→Guardar de siempre. */
function RegisterExternalStep({
  gateways,
  onCancel,
  onSaved,
}: {
  gateways: GatewayOut[];
  onCancel: () => void;
  onSaved: () => void;
}) {
  const queryClient = useQueryClient();
  const [gatewayId, setGatewayId] = useState("");
  const [transportType, setTransportType] = useState<"usb" | "tcp" | "http" | "mqtt">("usb");
  const [devices, setDevices] = useState<DeviceOut[] | null>(null);
  const [selectedPort, setSelectedPort] = useState("");
  const [net, setNet] = useState<NetState>(emptyNet());
  const [testResult, setTestResult] = useState<TestConnectionResultOut | null>(null);
  const [name, setName] = useState("");

  const connectionParams = (): Record<string, unknown> => {
    if (transportType === "usb") return selectedPort ? { device: selectedPort } : {};
    return netParams(transportType, net);
  };

  const discover = useMutation({
    mutationFn: () => discoverDevices(gatewayId),
    onSuccess: (found) => { setDevices(found); setTestResult(null); },
  });

  const test = useMutation({
    mutationFn: () =>
      testGatewayConnection(gatewayId, { transport_type: transportType, connection_params: connectionParams() }),
    onSuccess: (result) => {
      setTestResult(result);
      if (result.ok && !name) setName(result.local_short_name || result.local_long_name || gatewayId);
    },
  });

  const save = useMutation({
    mutationFn: () =>
      configureGateway(gatewayId, {
        name: name || gatewayId,
        transport_type: transportType,
        connection_params: connectionParams(),
        // Pre-registro sin proceso vivo aún (sin prueba de conexión): se guarda
        // deshabilitado para no intentar conectar contra nada; el usuario lo
        // habilita/conecta desde su panel cuando el proceso ya esté en marcha.
        enabled: testResult?.ok ?? isKnownCandidate,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["gateways"] });
      onSaved();
    },
  });

  const paramsReady = transportType === "usb" ? selectedPort !== "" : netReady(transportType, net);

  // Un gateway_id que nunca ha reportado heartbeat se puede guardar sin
  // probar conexión: es un pre-registro a la espera de que el proceso
  // correspondiente arranque con ese GATEWAY_ID. Uno ya visto en vivo exige
  // probar antes de guardar, como siempre.
  const existing = gateways.find((g) => g.gateway_id === gatewayId);
  const everSeen =
    !!existing &&
    (existing.status !== "unassigned" || existing.local_node_id != null || existing.last_connected_at != null);
  const isKnownCandidate = everSeen;
  const managedConflict = !!existing && existing.managed && existing.deleted_at == null && everSeen;

  return (
    <div className="panel-body">
      <p style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 0 }}>
        Para un proceso que arrancas tú (nativo fuera de Docker, otro host…) con su propio
        GATEWAY_ID — gateway-launcher no lo toca.
      </p>
      <div style={{ marginBottom: "0.8rem", display: "flex", gap: "0.6rem", alignItems: "center", flexWrap: "wrap" }}>
        <label style={{ fontSize: 12 }}>
          gateway_id{" "}
          <input
            className="input mono"
            style={{ width: 160 }}
            value={gatewayId}
            onChange={(e) => { setGatewayId(e.target.value); setDevices(null); setTestResult(null); }}
          />
        </label>
        <span className="seg">
          {(["usb", "tcp", "http", "mqtt"] as const).map((tt) => (
            <button
              key={tt}
              className={transportType === tt ? "on" : undefined}
              onClick={() => {
                setTransportType(tt);
                setTestResult(null);
                if (isNetType(tt)) setNet((prev) => ({ ...prev, port: DEFAULT_PORT[tt] }));
              }}
            >
              {TRANSPORT_LABEL[tt]}
            </button>
          ))}
        </span>
      </div>

      {isNetType(transportType) && (
        <NetFields type={transportType} net={net} onChange={(n) => { setNet(n); setTestResult(null); }} />
      )}

      {transportType === "usb" && (
        <div style={{ marginBottom: "0.8rem" }}>
          <button
            className="btn"
            disabled={!gatewayId.trim() || discover.isPending}
            onClick={() => discover.mutate()}
            title={!gatewayId.trim() ? "Escribe primero el gateway_id del proceso" : undefined}
          >
            {discover.isPending ? "Buscando…" : "⌕ Buscar dispositivos"}
          </button>
          {discover.isError && <p style={{ color: "var(--crit)", fontSize: 12 }}>{String(discover.error)}</p>}
          {devices != null && devices.length === 0 && (
            <p style={{ color: "var(--text-dim)", fontSize: 12 }}>
              Sin dispositivos detectados. Comprueba el cable o pulsa buscar de nuevo.
            </p>
          )}
          {devices != null && devices.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem", marginTop: "0.5rem" }}>
              {devices.map((d) => (
                <label
                  key={d.port}
                  style={{
                    display: "flex", gap: "0.6rem", alignItems: "center", cursor: "pointer", fontSize: 12,
                    border: "1px solid " + (selectedPort === d.port ? "var(--accent)" : "var(--border)"),
                    borderRadius: 3, padding: "0.4rem 0.6rem",
                    background: selectedPort === d.port ? "var(--accent-tint)" : "transparent",
                  }}
                >
                  <input
                    type="radio"
                    name="device"
                    checked={selectedPort === d.port}
                    onChange={() => { setSelectedPort(d.port); setTestResult(null); }}
                  />
                  <span className="mono">{d.port}</span>
                  <span style={{ color: "var(--text-dim)" }}>{d.description ?? "—"}</span>
                  {d.vid && d.pid && <span style={{ color: "var(--text-faint)" }}>VID:PID {d.vid}:{d.pid}</span>}
                  {d.serial_number && <span style={{ color: "var(--text-faint)" }}>S/N {d.serial_number}</span>}
                </label>
              ))}
            </div>
          )}
        </div>
      )}

      <div style={{ marginBottom: "0.8rem" }}>
        <button
          className="btn"
          disabled={!gatewayId.trim() || !paramsReady || test.isPending}
          onClick={() => test.mutate()}
        >
          {test.isPending ? "Probando…" : "▶ Probar conexión"}
        </button>
        {testResult && (
          testResult.ok ? (
            <p style={{ color: "var(--ok)", fontSize: 12 }}>
              ✓ Conectado — nodo {testResult.local_short_name ?? testResult.local_node_id}
              {testResult.local_hw_model ? ` (${testResult.local_hw_model})` : ""}
              {testResult.local_firmware_version ? ` · fw ${testResult.local_firmware_version}` : ""}
            </p>
          ) : (
            <p style={{ color: "var(--crit)", fontSize: 12 }}>✗ {testResult.error ?? "Fallo de conexión"}</p>
          )
        )}
      </div>

      <div>
        <input
          className="input"
          style={{ minWidth: 220 }}
          placeholder="Nombre (p. ej. Casa, Repetidor Norte…)"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button
          className={`btn${testResult?.ok || !isKnownCandidate ? " primary" : ""}`}
          style={{ marginLeft: "0.5rem" }}
          disabled={
            managedConflict ||
            (isKnownCandidate && !testResult?.ok) ||
            (transportType !== "usb" && !paramsReady) ||
            !name.trim() ||
            !gatewayId.trim() ||
            save.isPending
          }
          onClick={() => save.mutate()}
          title={
            managedConflict
              ? "Ya hay un enlace configurado con este identificador"
              : isKnownCandidate && !testResult?.ok
                ? "Prueba la conexión con éxito antes de guardar"
                : transportType !== "usb" && !paramsReady
                  ? "Introduce el host del nodo TCP"
                  : undefined
          }
        >
          Guardar enlace
        </button>
        <button className="btn ghost" style={{ marginLeft: "0.5rem" }} onClick={onCancel}>✕ Cancelar</button>
        {save.isError && <p style={{ color: "var(--crit)", fontSize: 12 }}>{String(save.error)}</p>}
        {managedConflict && (
          <p style={{ color: "var(--crit)", fontSize: 12 }}>
            «{gatewayId}» ya está configurado — edítalo desde su panel en vez de crear uno nuevo.
          </p>
        )}
      </div>
    </div>
  );
}

function AddGatewayWizard({
  gateways,
  onCancel,
  onSaved,
}: {
  gateways: GatewayOut[];
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [mode, setMode] = useState<"create" | "external">("create");
  return (
    <div className="panel" style={{ margin: "0.75rem", flexShrink: 0 }}>
      <div className="panel-head">
        <span className="panel-title">Nuevo enlace</span>
        <span className="seg">
          <button className={mode === "create" ? "on" : undefined} onClick={() => setMode("create")}>
            Crear contenedor
          </button>
          <button className={mode === "external" ? "on" : undefined} onClick={() => setMode("external")}>
            Registrar externo
          </button>
        </span>
        <span className="panel-count" />
      </div>
      {mode === "create" ? (
        <CreateContainerStep onCancel={onCancel} onCreated={onSaved} />
      ) : (
        <RegisterExternalStep gateways={gateways} onCancel={onCancel} onSaved={onSaved} />
      )}
    </div>
  );
}

// ── Módulo del rack: un gateway ya reportado (gestionado o no) ───────────────

function GatewayModule({
  gateway, stats, onMove,
}: {
  gateway: GatewayOut;
  stats?: GatewayStatsOut;
  /** Reordena el rack (ADR 0032); undefined = ese sentido no es posible. */
  onMove?: { up?: () => void; down?: () => void };
}) {
  const { canAdmin: canOperate } = useAuth();
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [editName, setEditName] = useState(gateway.name ?? "");
  const [editPriority, setEditPriority] = useState(String(gateway.priority));
  const [deleteArmed, setDeleteArmed] = useState(false);
  const [vn, setVn] = useState<VnState>(vnFromParams(gateway.connection_params));

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["gateways"] });

  const doImport = useMutation({ mutationFn: () => importGateway(gateway.gateway_id), onSuccess: invalidate });
  const doConnect = useMutation({ mutationFn: () => connectGateway(gateway.gateway_id), onSuccess: invalidate });
  const doDisconnect = useMutation({ mutationFn: () => disconnectGateway(gateway.gateway_id), onSuccess: invalidate });
  const doDelete = useMutation({ mutationFn: () => deleteGateway(gateway.gateway_id), onSuccess: invalidate });
  const doResync = useMutation({ mutationFn: () => resyncGateway(gateway.gateway_id), onSuccess: invalidate });
  const doReceiveOnly = useMutation({
    mutationFn: (value: boolean) => setGatewayReceiveOnly(gateway.gateway_id, value),
    onSuccess: invalidate,
  });
  const doPrimary = useMutation({
    mutationFn: (value: boolean) => setGatewayPrimary(gateway.gateway_id, value),
    onSuccess: invalidate,
  });
  const doSaveEdit = useMutation({
    mutationFn: () =>
      updateGateway(gateway.gateway_id, { name: editName, priority: Number(editPriority) || 0 }),
    onSuccess: invalidate,
  });
  const doSaveVn = useMutation({
    mutationFn: () =>
      updateGateway(gateway.gateway_id, {
        connection_params: withVn(gateway.connection_params, gateway.transport_type ?? gateway.transport, vn),
      }),
    onSuccess: invalidate,
  });
  const doToggleEnabled = useMutation({
    mutationFn: (enabled: boolean) => updateGateway(gateway.gateway_id, { enabled }),
    onSuccess: invalidate,
  });

  const statusColor = STATUS_COLOR[gateway.status] ?? "var(--crit)";

  return (
    <div className="panel" style={{ boxShadow: `inset 3px 0 0 ${gateway.enabled ? statusColor : "var(--border)"}` }}>
      <div
        className="panel-head"
        style={{ cursor: "pointer", flexWrap: "wrap", rowGap: 4, height: "auto", minHeight: 30, paddingBlock: 5 }}
        onClick={() => setExpanded((v) => !v)}
      >
        <span className="panel-title" style={{ color: "var(--text)" }}>
          {gateway.name ?? gateway.gateway_id}
        </span>
        <span className="chip">{TRANSPORT_LABEL[gateway.transport] ?? gateway.transport}</span>
        <StatusLight status={gateway.status} />
        {!gateway.managed && <span className="chip" style={{ color: "var(--warn)", borderColor: "var(--warn)" }}>sin configurar</span>}
        {gateway.managed && !gateway.enabled && <span className="chip">deshabilitado</span>}
        {gateway.container_managed && <span className="chip" title="Contenedor creado/destruido por gateway-launcher">contenedor</span>}
        {gateway.is_primary && <span className="chip" style={{ color: "var(--warn)", borderColor: "var(--warn)" }} title="Pasarela primaria: último recurso del enrutado cuando ninguna ha oído al nodo">★ primaria</span>}
        {gateway.virtual_node && (
          <span
            className="chip"
            title={`Nodo virtual activo en el puerto ${gateway.virtual_node.port}${gateway.virtual_node.allow_admin ? " (con administración permitida)" : ""}`}
          >
            ⇄ :{gateway.virtual_node.port} · {gateway.virtual_node.clients}
          </span>
        )}
        {!gateway.can_transmit && (
          <span
            className="chip"
            style={{ color: "var(--info, var(--accent))", borderColor: "var(--info, var(--accent))" }}
            title={
              gateway.receive_only
                ? "Marcada como solo recepción: no se le encolan operaciones que transmitan"
                : gateway.transport === "mqtt"
                  ? "Fuente MQTT: solo ingesta, no tiene radio"
                  : "El firmware del nodo tiene la transmisión desactivada (lora.tx_enabled = false)"
            }
          >
            👂 solo recepción
          </span>
        )}
        <span className="panel-count mono">{gateway.gateway_id} {expanded ? "▲" : "▼"}</span>
      </div>

      <div className="panel-body">
        {/* Cobertura de esta pasarela (M6.2, node_gateway_links) */}
        {stats && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(90px, 1fr))", gap: "0.6rem", marginBottom: expanded || !gateway.managed ? "0.75rem" : 0 }}>
            <Field k="Visibles" v={stats.nodes_visible} title="Nodos con escucha activa por esta pasarela" />
            <Field k="Exclusivos" v={stats.nodes_exclusive} title="Nodos que solo esta pasarela oye ahora mismo" />
            <Field k="Compartidos" v={stats.nodes_shared} title="Nodos que también oye otra pasarela" />
            <Field k="Primaria de" v={stats.primary_for} title="Nodos cuya pasarela primaria es esta" />
          </div>
        )}

        {canOperate && (
          <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", alignItems: "center", marginBottom: "0.75rem" }}>
            <button
              className="btn"
              disabled={doResync.isPending || gateway.status !== "connected" || gateway.transport === "mqtt"}
              onClick={() => doResync.mutate()}
              title="Relee el nodo local y republica su NodeDB sin cortar el enlace"
            >
              {doResync.isPending ? "Pidiendo…" : "↻ Resincronizar"}
            </button>
            <button
              className="btn"
              disabled={doReceiveOnly.isPending || gateway.transport === "mqtt"}
              onClick={() => doReceiveOnly.mutate(!gateway.receive_only)}
              title="Una pasarela de solo recepción sigue ingiriendo, pero no se le encolan operaciones que transmitan a la malla"
            >
              {gateway.receive_only ? "📡 Permitir transmitir" : "👂 Marcar solo recepción"}
            </button>
            <button
              className="btn"
              disabled={doPrimary.isPending}
              onClick={() => doPrimary.mutate(!gateway.is_primary)}
              title="La primaria es la pasarela de último recurso: se usa si ninguna ha oído al nodo"
            >
              {gateway.is_primary ? "☆ Quitar primaria" : "★ Hacer primaria"}
            </button>
            {onMove && (
              <span style={{ marginLeft: "auto", display: "inline-flex", gap: 2 }}>
                <button className="btn" disabled={!onMove.up} onClick={onMove.up} title="Subir">▲</button>
                <button className="btn" disabled={!onMove.down} onClick={onMove.down} title="Bajar">▼</button>
              </span>
            )}
          </div>
        )}
        {(doResync.isError || doReceiveOnly.isError || doPrimary.isError) && (
          <p style={{ color: "var(--crit)", fontSize: 12, marginTop: 0 }}>
            {String(doResync.error ?? doReceiveOnly.error ?? doPrimary.error)}
          </p>
        )}

        {/* Tres señales distintas (no mezclar): que la pasarela esté viva no
            depende de que haya tráfico, y viceversa. */}
        <ActivitySignals gateway={gateway} lastHeardFallback={stats?.last_heard_at ?? null} spaced={expanded || !gateway.managed} />

        {!gateway.managed && (
          <div>
            <p style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 0 }}>
              Late de verdad, pero todavía no está gestionada desde la aplicación.
            </p>
            {canOperate && (
              <button className="btn" disabled={doImport.isPending} onClick={() => doImport.mutate()}>
                ⬆ Reclamar esta pasarela
              </button>
            )}
            {doImport.isError && <p style={{ color: "var(--crit)", fontSize: 12 }}>{String(doImport.error)}</p>}
          </div>
        )}

        {expanded && gateway.managed && (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: "0.6rem" }}>
              <Field k="Nodo local" v={gateway.local_node_id ?? "—"} />
              <Field k="Nombre corto" v={gateway.local_short_name ?? "—"} />
              <Field k="Nombre largo" v={gateway.local_long_name ?? "—"} />
              <Field k="Hardware" v={gateway.local_hw_model ?? "—"} />
              <Field k="Firmware" v={gateway.local_firmware_version ?? "—"} />
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "0.6rem" }}>
              <Field k="Última conexión" v={relativeTime(gateway.last_connected_at)} />
              <Field k="Última desconexión" v={relativeTime(gateway.last_disconnected_at)} />
            </div>
            {gateway.last_error && gateway.status !== "connected" && (
              <div style={{ minWidth: 0 }}>
                <div className="microlabel">Último error · {relativeTime(gateway.last_error_at)}</div>
                <div
                  className="mono"
                  style={{ fontSize: 12, color: "var(--crit)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}
                >
                  {gateway.last_error}
                </div>
              </div>
            )}

            {!canOperate && (
              <p style={{ color: "var(--text-dim)", fontSize: 12, margin: 0 }}>
                🔒 Solo lectura — inicia sesión para editar o gestionar esta pasarela.
              </p>
            )}
            {canOperate && <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
              <input className="input" value={editName} onChange={(e) => setEditName(e.target.value)} />
              <input
                className="input"
                style={{ width: 70 }}
                type="number"
                value={editPriority}
                onChange={(e) => setEditPriority(e.target.value)}
                title="Prioridad (reservado para autoselección en Multi-Gateway)"
              />
              <button className="btn" disabled={doSaveEdit.isPending} onClick={() => doSaveEdit.mutate()}>
                Guardar cambios
              </button>
              <span style={{ marginLeft: "auto", display: "flex", gap: "0.4rem" }}>
                {gateway.status === "connected" || gateway.status === "connecting" || gateway.status === "reconnecting" ? (
                  <>
                    <button
                      className="btn"
                      disabled={doConnect.isPending}
                      onClick={() => doConnect.mutate()}
                      title="Cierra la conexión actual y la abre de nuevo (útil si el nodo se queda colgado)"
                    >
                      {doConnect.isPending ? "Reconectando…" : "Reconectar"}
                    </button>
                    <button className="btn" disabled={doDisconnect.isPending} onClick={() => doDisconnect.mutate()}>
                      Desconectar
                    </button>
                  </>
                ) : (
                  <button className="btn" disabled={doConnect.isPending} onClick={() => doConnect.mutate()}>
                    Conectar
                  </button>
                )}
                <button
                  className="btn"
                  disabled={doToggleEnabled.isPending}
                  onClick={() => doToggleEnabled.mutate(!gateway.enabled)}
                >
                  {gateway.enabled ? "Deshabilitar" : "Habilitar"}
                </button>
                {deleteArmed ? (
                  <button
                    className="btn danger"
                    onClick={() => doDelete.mutate()}
                    title={gateway.container_managed ? "También destruye su contenedor Docker" : undefined}
                  >
                    {gateway.container_managed ? "¿Eliminar y destruir contenedor?" : `¿Eliminar «${gateway.name}»?`}
                  </button>
                ) : (
                  <button className="btn" onClick={() => setDeleteArmed(true)}>
                    Eliminar
                  </button>
                )}
              </span>
            </div>}
            {canOperate && gateway.transport !== "mqtt" && gateway.transport !== "simulated" && (
              <div>
                <VirtualNodeFields vn={vn} onChange={setVn} />
                {JSON.stringify(vnFromParams(gateway.connection_params)) !== JSON.stringify(vn) && (
                  <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginTop: -4 }}>
                    <button className="btn primary" disabled={doSaveVn.isPending || !vnValid(vn)} onClick={() => doSaveVn.mutate()}>
                      {doSaveVn.isPending ? "Guardando…" : "Guardar nodo virtual"}
                    </button>
                    {gateway.container_managed &&
                    (vnFromParams(gateway.connection_params).enabled !== vn.enabled ||
                      vnFromParams(gateway.connection_params).port !== vn.port) ? (
                      <span style={{ fontSize: 11, color: "var(--text-faint)" }}>
                        Activar o mover el puerto recrea el contenedor (unos segundos sin conexión).
                      </span>
                    ) : null}
                  </div>
                )}
              </div>
            )}
            {(doConnect.isError || doDisconnect.isError || doDelete.isError || doSaveEdit.isError || doSaveVn.isError) && (
              <p style={{ color: "var(--crit)", fontSize: 12, margin: 0 }}>
                {String(doConnect.error ?? doDisconnect.error ?? doDelete.error ?? doSaveEdit.error ?? doSaveVn.error)}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Workspace ────────────────────────────────────────────────────────────────

export function GatewaysView() {
  const { canAdmin: canOperate } = useAuth();
  // include_deleted: una pasarela eliminada (borrado lógico) sigue siendo un
  // candidato válido para "+ Añadir enlace" — el proceso puede seguir vivo,
  // solo se retiró de la gestión activa (ver ADR 0021 §6).
  const gateways = useQuery({
    queryKey: ["gateways", "all"],
    queryFn: () => fetchGateways(true),
    refetchInterval: 15_000,
  });
  const stats = useQuery({
    queryKey: ["gateway-stats"],
    queryFn: () => fetchGatewayStats(),
    refetchInterval: 15_000,
  });
  const [wizardOpen, setWizardOpen] = useState(false);
  const queryClient = useQueryClient();
  const reorder = useMutation({
    mutationFn: (ids: string[]) => reorderGateways(ids),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["gateways"] }),
  });

  const all = gateways.data ?? [];
  const list = all.filter((g) => g.deleted_at == null);
  const deleted = all.filter((g) => g.deleted_at != null);
  const statsById = new Map((stats.data?.gateways ?? []).map((g) => [g.gateway_id, g]));
  const connected = list.filter((g) => g.status === "connected").length;

  return (
    <div className="ws">
      <div className="toolbar">
        <span className="microlabel">Gateways de malla</span>
        <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>
          {connected}/{list.length} conectados
        </span>
        <span style={{ marginLeft: "auto" }} />
        {canOperate ? (
          <button className="btn primary" onClick={() => setWizardOpen(true)}>
            + Añadir enlace
          </button>
        ) : (
          <span style={{ fontSize: 11, color: "var(--text-dim)" }}>🔒 Solo lectura</span>
        )}
      </div>

      {wizardOpen ? (
        <div className="ws-scroll">
          <AddGatewayWizard
            gateways={all}
            onCancel={() => setWizardOpen(false)}
            onSaved={() => setWizardOpen(false)}
          />
        </div>
      ) : (
        <div className="ws-scroll" style={{ padding: "0.75rem" }}>
          {gateways.isLoading && <div className="empty">Cargando…</div>}
          {list.length === 0 && !gateways.isLoading && (
            <div className="empty">Ninguna pasarela ha reportado actividad todavía.</div>
          )}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(min(430px, 100%), 1fr))",
              gap: "0.75rem",
              alignItems: "start",
            }}
          >
            {list.map((g, i) => {
              const swap = (to: number) => () => {
                const ids = list.map((x) => x.gateway_id);
                [ids[i], ids[to]] = [ids[to], ids[i]];
                reorder.mutate(ids);
              };
              return (
                <GatewayModule
                  key={g.gateway_id}
                  gateway={g}
                  stats={statsById.get(g.gateway_id)}
                  onMove={{ up: i > 0 ? swap(i - 1) : undefined, down: i < list.length - 1 ? swap(i + 1) : undefined }}
                />
              );
            })}
          </div>

          {deleted.length > 0 && (
            <p style={{ color: "var(--text-faint)", fontSize: 12 }}>
              Eliminados: {deleted.map((g) => g.name ?? g.gateway_id).join(", ")} — usa «+ Añadir enlace»
              para volver a configurar el mismo proceso.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

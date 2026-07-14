import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  configureGateway,
  connectGateway,
  deleteGateway,
  disconnectGateway,
  discoverDevices,
  fetchGateways,
  fetchGatewayStats,
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
 * Enlaces (identidad v0.8): las pasarelas dejan de ser tarjetas apiladas y
 * pasan a ser módulos de un rack — un panel por enlace con luz de estado,
 * telemetría de cobertura M6.2 y controles inline. La lógica (asistente
 * Buscar→Probar→Guardar, conectar/desconectar, borrado lógico) es la de M5,
 * intacta; solo cambia la presentación.
 */

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
  simulated: "SIM",
};

/** Par clave/valor en mono, la unidad de lectura de los módulos del rack. */
function Field({ k, v, title }: { k: string; v: React.ReactNode; title?: string }) {
  return (
    <div title={title} style={{ minWidth: 0 }}>
      <div className="microlabel">{k}</div>
      <div className="mono" style={{ fontSize: 12, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {v}
      </div>
    </div>
  );
}

// ── Asistente: Buscar dispositivos → Seleccionar → Probar conexión → Guardar ─

/** Propone una semilla exclusiva no usada por ninguna pasarela simulada ya
 * configurada (M6.2): dos procesos con la misma semilla generan la MISMA
 * malla ficticia y se pisan. */
function suggestSeed(gateways: GatewayOut[]): number {
  const used = new Set(
    gateways
      .map((g) => Number(g.connection_params?.seed))
      .filter((s) => Number.isFinite(s)),
  );
  used.add(42); // valor por defecto del proceso: evitar chocar con .env
  let seed = 43;
  while (used.has(seed)) seed += 1;
  return seed;
}

function AddGatewayWizard({
  initialGatewayId,
  candidates,
  gateways,
  onCancel,
  onSaved,
}: {
  initialGatewayId: string;
  candidates: string[];
  gateways: GatewayOut[];
  onCancel: () => void;
  onSaved: () => void;
}) {
  const queryClient = useQueryClient();
  const [gatewayId, setGatewayId] = useState(initialGatewayId);
  const [transportType, setTransportType] = useState<"usb" | "tcp" | "simulated">("usb");
  const [devices, setDevices] = useState<DeviceOut[] | null>(null);
  const [selectedPort, setSelectedPort] = useState("");
  const [tcpHost, setTcpHost] = useState("");
  const [tcpPort, setTcpPort] = useState("4403");
  const [simSeed, setSimSeed] = useState(String(suggestSeed(gateways)));
  const [simNodeCount, setSimNodeCount] = useState("12");
  const [simSharedSeed, setSimSharedSeed] = useState("0");
  const [simSharedNodeCount, setSimSharedNodeCount] = useState("4");
  const [testResult, setTestResult] = useState<TestConnectionResultOut | null>(null);
  const [name, setName] = useState("");

  const connectionParams = (): Record<string, unknown> => {
    if (transportType === "usb") return selectedPort ? { device: selectedPort } : {};
    if (transportType === "tcp") return { host: tcpHost.trim(), port: Number(tcpPort) || 4403 };
    return {
      seed: Number(simSeed) || 42,
      node_count: Number(simNodeCount) || 12,
      shared_seed: Number(simSharedSeed) || 0,
      shared_node_count: Number(simSharedNodeCount) || 4,
    };
  };

  const discover = useMutation({
    mutationFn: () => discoverDevices(gatewayId),
    onSuccess: (found) => {
      setDevices(found);
      setTestResult(null);
    },
  });

  const test = useMutation({
    mutationFn: () =>
      testGatewayConnection(gatewayId, {
        transport_type: transportType,
        connection_params: connectionParams(),
      }),
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

  const paramsReady =
    transportType === "usb"
      ? selectedPort !== ""
      : transportType === "tcp"
        ? tcpHost.trim() !== ""
        : simSeed.trim() !== "";

  // Un gateway_id nuevo (que nunca ha reportado heartbeat) se puede guardar
  // sin probar conexión: es un pre-registro a la espera de que el proceso
  // correspondiente arranque con ese GATEWAY_ID. Uno ya conocido por
  // heartbeat (candidato) exige probar antes de guardar, como siempre.
  const existing = gateways.find((g) => g.gateway_id === gatewayId);
  const isKnownCandidate = candidates.includes(gatewayId);
  const managedConflict = !!existing && existing.managed && existing.deleted_at == null;

  return (
    <div className="panel" style={{ margin: "0.75rem", flexShrink: 0 }}>
      <div className="panel-head">
        <span className="panel-title">Nuevo enlace</span>
        <input
          className="input mono"
          style={{ width: 170 }}
          list="gateway-id-candidates"
          placeholder="gateway_id (p. ej. gw-02)"
          value={gatewayId}
          onChange={(e) => {
            setGatewayId(e.target.value.trim());
            setDevices(null);
            setTestResult(null);
          }}
        />
        <datalist id="gateway-id-candidates">
          {candidates.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
        <span className="seg">
          {(["usb", "tcp", "simulated"] as const).map((tt) => (
            <button
              key={tt}
              className={transportType === tt ? "on" : undefined}
              onClick={() => {
                setTransportType(tt);
                setTestResult(null);
              }}
            >
              {TRANSPORT_LABEL[tt]}
            </button>
          ))}
        </span>
        <span className="panel-count" />
        <button className="btn ghost" onClick={onCancel}>✕ Cancelar</button>
      </div>
      <div className="panel-body">
        {transportType === "simulated" && (
          <div style={{ marginBottom: "0.8rem" }}>
            <p style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 0 }}>
              1 · Parámetros de la malla simulada. La semilla propuesta no está usada por ninguna otra
              pasarela; una <em>semilla compartida</em> igual en varias pasarelas genera nodos comunes
              (SHRxx) para validar Multi-Gateway.
            </p>
            <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", alignItems: "center", fontSize: 12 }}>
              <label>Semilla <input className="input" style={{ width: 80 }} type="number" value={simSeed} onChange={(e) => { setSimSeed(e.target.value); setTestResult(null); }} /></label>
              <label>Nodos <input className="input" style={{ width: 70 }} type="number" value={simNodeCount} onChange={(e) => { setSimNodeCount(e.target.value); setTestResult(null); }} /></label>
              <label title="0 = sin nodos compartidos">Semilla compartida <input className="input" style={{ width: 80 }} type="number" value={simSharedSeed} onChange={(e) => { setSimSharedSeed(e.target.value); setTestResult(null); }} /></label>
              <label>Nodos compartidos <input className="input" style={{ width: 70 }} type="number" value={simSharedNodeCount} onChange={(e) => { setSimSharedNodeCount(e.target.value); setTestResult(null); }} /></label>
            </div>
          </div>
        )}

        {transportType === "tcp" && (
          <div style={{ marginBottom: "0.8rem" }}>
            <p style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 0 }}>
              1 · Dirección del nodo en la red (WiFi/Ethernet). Sin búsqueda automática: introduce el
              host manualmente. El firmware solo admite un cliente TCP a la vez — cierra la app
              oficial si está conectada a ese nodo.
            </p>
            <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", alignItems: "center", fontSize: 12 }}>
              <label>
                Host{" "}
                <input
                  className="input"
                  style={{ width: 190, fontFamily: "var(--font-mono)" }}
                  placeholder="192.168.1.50 o meshtastic.local"
                  value={tcpHost}
                  onChange={(e) => { setTcpHost(e.target.value); setTestResult(null); }}
                />
              </label>
              <label>
                Puerto{" "}
                <input
                  className="input"
                  style={{ width: 80 }}
                  type="number"
                  value={tcpPort}
                  onChange={(e) => { setTcpPort(e.target.value); setTestResult(null); }}
                />
              </label>
            </div>
          </div>
        )}

        {transportType === "usb" && (
          <div style={{ marginBottom: "0.8rem" }}>
            <p style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 0 }}>
              1 · Buscar dispositivos USB conectados a esta pasarela.
            </p>
            <button
              className="btn"
              disabled={!gatewayId.trim() || discover.isPending}
              onClick={() => discover.mutate()}
              title={!gatewayId.trim() ? "Escribe primero el gateway_id del proceso a buscar" : undefined}
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
          <p style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 0 }}>2 · Probar la conexión antes de guardar.</p>
          <button
            className="btn"
            disabled={!gatewayId.trim() || !paramsReady || test.isPending}
            onClick={() => test.mutate()}
            title={!gatewayId.trim() ? "Escribe primero el gateway_id del proceso a probar" : undefined}
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
          <p style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 0 }}>3 · Nombre y guardar.</p>
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
            disabled={managedConflict || (isKnownCandidate && !testResult?.ok) || !name.trim() || !gatewayId.trim() || save.isPending}
            onClick={() => save.mutate()}
            title={
              managedConflict
                ? "Ya hay un enlace configurado con este identificador"
                : isKnownCandidate && !testResult?.ok
                  ? "Prueba la conexión con éxito antes de guardar"
                  : undefined
            }
          >
            Guardar enlace
          </button>
          {save.isError && <p style={{ color: "var(--crit)", fontSize: 12 }}>{String(save.error)}</p>}
          {managedConflict && (
            <p style={{ color: "var(--crit)", fontSize: 12 }}>
              Ya existe un enlace configurado con «{gatewayId}» — edítalo desde su panel en vez de crear uno nuevo.
            </p>
          )}
          {!managedConflict && !isKnownCandidate && gatewayId.trim() && (
            <p style={{ color: "var(--text-dim)", fontSize: 12 }}>
              «{gatewayId}» todavía no ha reportado actividad: se guardará esta configuración a la espera de que
              arranques ese proceso con <span className="mono">GATEWAY_ID={gatewayId}</span>. Puedes probar la
              conexión igualmente si el proceso ya está en marcha.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Módulo del rack: un gateway ya reportado (gestionado o no) ───────────────

function GatewayModule({ gateway, stats }: { gateway: GatewayOut; stats?: GatewayStatsOut }) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [editName, setEditName] = useState(gateway.name ?? "");
  const [editPriority, setEditPriority] = useState(String(gateway.priority));
  const [deleteArmed, setDeleteArmed] = useState(false);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["gateways"] });

  const doImport = useMutation({ mutationFn: () => importGateway(gateway.gateway_id), onSuccess: invalidate });
  const doConnect = useMutation({ mutationFn: () => connectGateway(gateway.gateway_id), onSuccess: invalidate });
  const doDisconnect = useMutation({ mutationFn: () => disconnectGateway(gateway.gateway_id), onSuccess: invalidate });
  const doDelete = useMutation({ mutationFn: () => deleteGateway(gateway.gateway_id), onSuccess: invalidate });
  const doSaveEdit = useMutation({
    mutationFn: () =>
      updateGateway(gateway.gateway_id, { name: editName, priority: Number(editPriority) || 0 }),
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
        style={{ cursor: "pointer" }}
        onClick={() => setExpanded((v) => !v)}
      >
        <span className="panel-title" style={{ color: "var(--text)" }}>
          {gateway.name ?? gateway.gateway_id}
        </span>
        <span className="chip">{TRANSPORT_LABEL[gateway.transport] ?? gateway.transport}</span>
        <StatusLight status={gateway.status} />
        {!gateway.managed && <span className="chip" style={{ color: "var(--warn)", borderColor: "var(--warn)" }}>sin configurar</span>}
        {gateway.managed && !gateway.enabled && <span className="chip">deshabilitado</span>}
        <span className="panel-count">{gateway.gateway_id} {expanded ? "▲" : "▼"}</span>
      </div>

      <div className="panel-body">
        {/* Cobertura de esta pasarela (M6.2, node_gateway_links) */}
        {stats && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(90px, 1fr))", gap: "0.6rem", marginBottom: expanded || !gateway.managed ? "0.75rem" : 0 }}>
            <Field k="Visibles" v={stats.nodes_visible} title="Nodos con escucha activa por esta pasarela" />
            <Field k="Exclusivos" v={stats.nodes_exclusive} title="Nodos que solo esta pasarela oye ahora mismo" />
            <Field k="Compartidos" v={stats.nodes_shared} title="Nodos que también oye otra pasarela" />
            <Field k="Primaria de" v={stats.primary_for} title="Nodos cuya pasarela primaria es esta" />
            <Field k="Actividad" v={relativeTime(stats.last_heard_at)} />
          </div>
        )}

        {!gateway.managed && (
          <div>
            <p style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 0 }}>
              Pasarela detectada por heartbeat (configuración de <span className="mono">.env</span>), aún sin
              gestionar desde la aplicación.
            </p>
            <button className="btn" disabled={doImport.isPending} onClick={() => doImport.mutate()}>
              ⬆ Importar configuración actual
            </button>
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
              <Field
                k="Último error"
                v={gateway.last_error ? `${gateway.last_error} (${relativeTime(gateway.last_error_at)})` : "—"}
              />
            </div>

            <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
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
                  <button className="btn" disabled={doDisconnect.isPending} onClick={() => doDisconnect.mutate()}>
                    Desconectar
                  </button>
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
                  <button className="btn danger" onClick={() => doDelete.mutate()}>
                    ¿Eliminar «{gateway.name}»?
                  </button>
                ) : (
                  <button className="btn" onClick={() => setDeleteArmed(true)}>
                    Eliminar
                  </button>
                )}
              </span>
            </div>
            {(doConnect.isError || doDisconnect.isError || doDelete.isError || doSaveEdit.isError) && (
              <p style={{ color: "var(--crit)", fontSize: 12, margin: 0 }}>
                {String(doConnect.error ?? doDisconnect.error ?? doDelete.error ?? doSaveEdit.error)}
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

  const all = gateways.data ?? [];
  const list = all.filter((g) => g.deleted_at == null);
  const deleted = all.filter((g) => g.deleted_at != null);
  // M6.2: con varios procesos sin configurar a la vez, el asistente ofrece
  // un selector explícito en vez de auto-elegir el primero.
  const candidates = all.filter((g) => !g.managed || g.deleted_at != null).map((g) => g.gateway_id);
  const statsById = new Map((stats.data?.gateways ?? []).map((g) => [g.gateway_id, g]));
  const connected = list.filter((g) => g.status === "connected").length;

  return (
    <div className="ws">
      <div className="toolbar">
        <span className="microlabel">Enlaces de malla</span>
        <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>
          {connected}/{list.length} conectados
        </span>
        <span style={{ marginLeft: "auto" }} />
        <button className="btn primary" onClick={() => setWizardOpen(true)}>
          + Añadir enlace
        </button>
      </div>

      {wizardOpen ? (
        <div className="ws-scroll">
          <AddGatewayWizard
            initialGatewayId={candidates[0] ?? ""}
            candidates={candidates}
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
              gridTemplateColumns: "repeat(auto-fill, minmax(430px, 1fr))",
              gap: "0.75rem",
              alignItems: "start",
            }}
          >
            {list.map((g) => (
              <GatewayModule key={g.gateway_id} gateway={g} stats={statsById.get(g.gateway_id)} />
            ))}
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

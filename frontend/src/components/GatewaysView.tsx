import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type CSSProperties } from "react";
import {
  configureGateway,
  connectGateway,
  deleteGateway,
  disconnectGateway,
  discoverDevices,
  fetchGateways,
  importGateway,
  testGatewayConnection,
  updateGateway,
  type DeviceOut,
  type GatewayOut,
  type GatewayStatus,
  type TestConnectionResultOut,
} from "../api/client";
import { styles } from "../styles";

const input: CSSProperties = {
  background: "#0d1117",
  border: "1px solid #30363d",
  color: "#e6edf3",
  borderRadius: 6,
  padding: "0.3rem 0.5rem",
};
const btn: CSSProperties = { ...input, cursor: "pointer" };

const STATUS_DOT: Record<string, string> = {
  connected: "🟢",
  connecting: "🟡",
  reconnecting: "🟡",
  disconnected: "🔴",
  error: "🔴",
  unassigned: "🔴",
};

const STATUS_LABEL: Record<string, string> = {
  connected: "Conectado",
  connecting: "Conectando…",
  reconnecting: "Reconectando…",
  disconnected: "Desconectado",
  error: "Error",
  unassigned: "Sin conexión",
};

function StatusBadge({ status }: { status: GatewayStatus | string }) {
  return (
    <span>
      {STATUS_DOT[status] ?? "🔴"} {STATUS_LABEL[status] ?? status}
    </span>
  );
}

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `hace ${Math.round(seconds)}s`;
  if (seconds < 3600) return `hace ${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `hace ${Math.round(seconds / 3600)}h`;
  return `hace ${Math.round(seconds / 86400)}d`;
}

const TRANSPORT_LABEL: Record<string, string> = {
  usb: "USB",
  serial: "USB",
  tcp: "TCP",
  http: "HTTP",
  simulated: "Simulado",
};

// ── Asistente: Buscar dispositivos → Seleccionar → Probar conexión → Guardar ─

function AddGatewayWizard({
  gatewayId,
  onCancel,
  onSaved,
}: {
  gatewayId: string;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const queryClient = useQueryClient();
  const [devices, setDevices] = useState<DeviceOut[] | null>(null);
  const [selectedPort, setSelectedPort] = useState("");
  const [testResult, setTestResult] = useState<TestConnectionResultOut | null>(null);
  const [name, setName] = useState("");

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
        transport_type: "usb",
        connection_params: selectedPort ? { device: selectedPort } : {},
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
        transport_type: "usb",
        connection_params: selectedPort ? { device: selectedPort } : {},
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["gateways"] });
      onSaved();
    },
  });

  return (
    <div style={styles.card}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.8rem" }}>
        <h3 style={{ margin: 0 }}>Añadir gateway ({gatewayId})</h3>
        <button style={{ ...btn, marginLeft: "auto" }} onClick={onCancel}>✕ Cancelar</button>
      </div>

      <div style={{ margin: "0.8rem 0" }}>
        <p style={styles.dim}>1. Buscar dispositivos USB conectados a esta pasarela.</p>
        <button style={btn} disabled={discover.isPending} onClick={() => discover.mutate()}>
          {discover.isPending ? "Buscando…" : "🔍 Buscar dispositivos"}
        </button>
        {discover.isError && <p style={styles.bad}>{String(discover.error)}</p>}
        {devices != null && devices.length === 0 && (
          <p style={styles.dim}>Sin dispositivos detectados. Comprueba el cable o pulsa buscar de nuevo.</p>
        )}
        {devices != null && devices.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem", marginTop: "0.5rem" }}>
            {devices.map((d) => (
              <label
                key={d.port}
                style={{
                  display: "flex", gap: "0.6rem", alignItems: "center", cursor: "pointer",
                  border: "1px solid " + (selectedPort === d.port ? "#1f6feb" : "#30363d"),
                  borderRadius: 6, padding: "0.4rem 0.6rem",
                }}
              >
                <input
                  type="radio"
                  name="device"
                  checked={selectedPort === d.port}
                  onChange={() => { setSelectedPort(d.port); setTestResult(null); }}
                />
                <span style={styles.mono}>{d.port}</span>
                <span style={styles.dim}>{d.description ?? "—"}</span>
                {d.vid && d.pid && <span style={styles.dim}>VID:PID {d.vid}:{d.pid}</span>}
                {d.serial_number && <span style={styles.dim}>S/N {d.serial_number}</span>}
              </label>
            ))}
          </div>
        )}
      </div>

      <div style={{ margin: "0.8rem 0" }}>
        <p style={styles.dim}>2. Probar la conexión antes de guardar.</p>
        <button style={btn} disabled={!selectedPort || test.isPending} onClick={() => test.mutate()}>
          {test.isPending ? "Probando…" : "▶ Probar conexión"}
        </button>
        {testResult && (
          testResult.ok ? (
            <p style={styles.ok}>
              ✓ Conectado — nodo {testResult.local_short_name ?? testResult.local_node_id}
              {testResult.local_hw_model ? ` (${testResult.local_hw_model})` : ""}
              {testResult.local_firmware_version ? ` · fw ${testResult.local_firmware_version}` : ""}
            </p>
          ) : (
            <p style={styles.bad}>✗ {testResult.error ?? "Fallo de conexión"}</p>
          )
        )}
      </div>

      <div style={{ margin: "0.8rem 0" }}>
        <p style={styles.dim}>3. Nombre y guardar.</p>
        <input
          style={{ ...input, minWidth: 220 }}
          placeholder="Nombre (p. ej. Casa, Repetidor Norte…)"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button
          style={{ ...btn, marginLeft: "0.5rem", background: testResult?.ok ? "#1f6feb" : "transparent" }}
          disabled={!testResult?.ok || !name.trim() || save.isPending}
          onClick={() => save.mutate()}
          title={!testResult?.ok ? "Prueba la conexión con éxito antes de guardar" : undefined}
        >
          💾 Guardar
        </button>
        {save.isError && <p style={styles.bad}>{String(save.error)}</p>}
      </div>
    </div>
  );
}

// ── Tarjeta de un gateway ya reportado (gestionado o no) ─────────────────────

function GatewayCard({ gateway }: { gateway: GatewayOut }) {
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

  return (
    <div style={{ ...styles.card, marginBottom: "0.6rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.8rem", cursor: "pointer" }} onClick={() => setExpanded((v) => !v)}>
        <strong>{gateway.name ?? gateway.gateway_id}</strong>
        <span style={styles.dim}>{TRANSPORT_LABEL[gateway.transport] ?? gateway.transport}</span>
        <StatusBadge status={gateway.status} />
        {!gateway.managed && <span style={{ color: "#d29922" }}>sin configurar</span>}
        {gateway.managed && !gateway.enabled && <span style={styles.dim}>deshabilitado</span>}
        <span style={{ marginLeft: "auto", ...styles.dim, fontSize: "0.8rem" }}>{expanded ? "▲" : "▼"}</span>
      </div>

      {!gateway.managed && (
        <div style={{ marginTop: "0.6rem" }}>
          <p style={styles.dim}>
            Pasarela detectada por heartbeat (configuración de <span style={styles.mono}>.env</span>), aún sin
            gestionar desde la aplicación.
          </p>
          <button style={btn} disabled={doImport.isPending} onClick={() => doImport.mutate()}>
            ⬆ Importar configuración actual
          </button>
          {doImport.isError && <p style={styles.bad}>{String(doImport.error)}</p>}
        </div>
      )}

      {expanded && gateway.managed && (
        <div style={{ marginTop: "0.8rem", display: "flex", flexDirection: "column", gap: "0.6rem" }}>
          <div style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap", fontSize: "0.9rem" }}>
            <span>Nodo local: <span style={styles.mono}>{gateway.local_node_id ?? "—"}</span></span>
            <span>Nombre corto: {gateway.local_short_name ?? "—"}</span>
            <span>Nombre largo: {gateway.local_long_name ?? "—"}</span>
            <span>Hardware: {gateway.local_hw_model ?? "—"}</span>
            <span>Firmware: {gateway.local_firmware_version ?? "—"}</span>
          </div>
          <div style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap", fontSize: "0.85rem", ...styles.dim }}>
            <span>Última conexión: {relativeTime(gateway.last_connected_at)}</span>
            <span>Última desconexión: {relativeTime(gateway.last_disconnected_at)}</span>
            <span>
              Último error: {gateway.last_error ? `${gateway.last_error} (${relativeTime(gateway.last_error_at)})` : "—"}
            </span>
          </div>

          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
            <input style={input} value={editName} onChange={(e) => setEditName(e.target.value)} />
            <input
              style={{ ...input, width: 70 }}
              type="number"
              value={editPriority}
              onChange={(e) => setEditPriority(e.target.value)}
              title="Prioridad (reservado para autoselección en Multi-Gateway)"
            />
            <button style={btn} disabled={doSaveEdit.isPending} onClick={() => doSaveEdit.mutate()}>
              Guardar cambios
            </button>
            <span style={{ marginLeft: "auto", display: "flex", gap: "0.4rem" }}>
              {gateway.status === "connected" || gateway.status === "connecting" || gateway.status === "reconnecting" ? (
                <button style={btn} disabled={doDisconnect.isPending} onClick={() => doDisconnect.mutate()}>
                  Desconectar
                </button>
              ) : (
                <button style={btn} disabled={doConnect.isPending} onClick={() => doConnect.mutate()}>
                  Conectar
                </button>
              )}
              <button
                style={btn}
                disabled={doToggleEnabled.isPending}
                onClick={() => doToggleEnabled.mutate(!gateway.enabled)}
              >
                {gateway.enabled ? "Deshabilitar" : "Habilitar"}
              </button>
              {deleteArmed ? (
                <button style={{ ...btn, background: "#b62324" }} onClick={() => doDelete.mutate()}>
                  ¿Eliminar «{gateway.name}»?
                </button>
              ) : (
                <button style={btn} onClick={() => setDeleteArmed(true)}>
                  Eliminar
                </button>
              )}
            </span>
          </div>
          {(doConnect.isError || doDisconnect.isError || doDelete.isError || doSaveEdit.isError) && (
            <p style={styles.bad}>
              {String(doConnect.error ?? doDisconnect.error ?? doDelete.error ?? doSaveEdit.error)}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Vista principal ──────────────────────────────────────────────────────────

export function GatewaysView() {
  // include_deleted: una pasarela eliminada (borrado lógico) sigue siendo un
  // candidato válido para "+ Añadir gateway" — el proceso puede seguir vivo,
  // solo se retiró de la gestión activa (ver ADR 0021 §6).
  const gateways = useQuery({
    queryKey: ["gateways", "all"],
    queryFn: () => fetchGateways(true),
    refetchInterval: 15_000,
  });
  const [wizardFor, setWizardFor] = useState<string | null>(null);

  const all = gateways.data ?? [];
  const list = all.filter((g) => g.deleted_at == null);
  const deleted = all.filter((g) => g.deleted_at != null);
  const unmanagedCandidate = all.find((g) => !g.managed || g.deleted_at != null)?.gateway_id ?? null;

  if (wizardFor) {
    return (
      <AddGatewayWizard
        gatewayId={wizardFor}
        onCancel={() => setWizardFor(null)}
        onSaved={() => setWizardFor(null)}
      />
    );
  }

  return (
    <div>
      <div style={{ ...styles.card, display: "flex", alignItems: "center", gap: "0.8rem" }}>
        <h2 style={{ margin: 0 }}>Gateways</h2>
        <button
          style={{ ...btn, marginLeft: "auto", background: unmanagedCandidate ? "#1f6feb" : "transparent" }}
          disabled={!unmanagedCandidate}
          onClick={() => unmanagedCandidate && setWizardFor(unmanagedCandidate)}
          title={
            unmanagedCandidate
              ? undefined
              : "Todos los procesos de pasarela detectados ya están configurados"
          }
        >
          + Añadir gateway
        </button>
      </div>

      {gateways.isLoading && <p style={styles.dim}>Cargando…</p>}
      {list.length === 0 && !gateways.isLoading && (
        <p style={styles.dim}>Ninguna pasarela ha reportado actividad todavía.</p>
      )}
      {list.map((g) => (
        <GatewayCard key={g.gateway_id} gateway={g} />
      ))}

      {deleted.length > 0 && (
        <p style={{ ...styles.dim, fontSize: "0.85rem" }}>
          Eliminados: {deleted.map((g) => g.name ?? g.gateway_id).join(", ")} — usa «+ Añadir gateway» para
          volver a configurar el mismo proceso.
        </p>
      )}
    </div>
  );
}

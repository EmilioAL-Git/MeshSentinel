import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type CSSProperties } from "react";
import {
  createChannel,
  deleteChannel,
  fetchAlertRules,
  fetchAlerts,
  fetchChannels,
  patchAlertRule,
  testChannel,
  type AlertOut,
  type Severity,
} from "../api/client";
import { styles } from "../styles";

const SEVERITY_STYLE: Record<Severity, CSSProperties> = {
  INFO: { background: "transparent", color: "var(--text-dim)", border: "1px solid var(--border)" },
  WARNING: { background: "var(--warn-tint)", color: "var(--warn)", border: "1px solid var(--warn)" },
  CRITICAL: { background: "var(--crit-tint)", color: "var(--crit)", border: "1px solid var(--crit)" },
};

const badge = (extra: CSSProperties): CSSProperties => ({
  borderRadius: 12,
  padding: "0.1rem 0.6rem",
  fontSize: "0.75rem",
  ...extra,
});

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `hace ${Math.round(seconds)}s`;
  if (seconds < 3600) return `hace ${Math.round(seconds / 60)}m`;
  return `hace ${Math.round(seconds / 3600)}h`;
}

function AlertsTable({ alerts, emptyText }: { alerts: AlertOut[]; emptyText: string }) {
  if (alerts.length === 0) return <p style={styles.dim}>{emptyText}</p>;
  return (
    <table style={styles.table}>
      <thead>
        <tr>
          <th style={styles.th}>Severidad</th>
          <th style={styles.th}>Regla</th>
          <th style={styles.th}>Mensaje</th>
          <th style={styles.th}>Desde</th>
          <th style={styles.th}>Estado</th>
        </tr>
      </thead>
      <tbody>
        {alerts.map((a) => (
          <tr key={a.id}>
            <td style={styles.td}>
              <span style={badge(SEVERITY_STYLE[a.severity])}>{a.severity}</span>
            </td>
            <td style={styles.td}>{a.rule_name}</td>
            <td style={styles.td}>{a.message}</td>
            <td style={styles.td}>{relativeTime(a.fired_at)}</td>
            <td style={styles.td}>
              {a.status === "resolved" ? `resuelta ${relativeTime(a.resolved_at)}` : a.status}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function AlertsView() {
  const queryClient = useQueryClient();
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["alerts"] });
    queryClient.invalidateQueries({ queryKey: ["alert-rules"] });
    queryClient.invalidateQueries({ queryKey: ["channels"] });
  };

  const alerts = useQuery({ queryKey: ["alerts"], queryFn: () => fetchAlerts(undefined, 100), refetchInterval: 30_000 });
  const rules = useQuery({ queryKey: ["alert-rules"], queryFn: fetchAlertRules });
  const channels = useQuery({ queryKey: ["channels"], queryFn: fetchChannels });

  const toggleRule = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => patchAlertRule(id, { enabled }),
    onSettled: invalidate,
  });
  const addChannel = useMutation({ mutationFn: createChannel, onSettled: invalidate });
  const removeChannel = useMutation({ mutationFn: deleteChannel, onSettled: invalidate });
  const test = useMutation({ mutationFn: testChannel });

  const [chName, setChName] = useState("");
  const [chType, setChType] = useState<"webhook" | "ntfy">("ntfy");
  const [chTarget, setChTarget] = useState("");

  const all = alerts.data ?? [];
  const active = all.filter((a) => a.status !== "resolved");
  const resolved = all.filter((a) => a.status === "resolved").slice(0, 20);

  const inputStyle: CSSProperties = {
    background: "var(--bg)",
    border: "1px solid var(--border)",
    color: "var(--text)",
    borderRadius: 6,
    padding: "0.3rem 0.5rem",
  };

  return (
    <div>
      <div style={styles.card}>
        <h2 style={{ marginTop: 0 }}>Alertas activas ({active.length})</h2>
        {alerts.isLoading ? <p>Cargando…</p> : <AlertsTable alerts={active} emptyText="Sin alertas activas. Red dentro de los umbrales." />}
      </div>

      <div style={styles.layout}>
        <div style={styles.card}>
          <h2 style={{ marginTop: 0 }}>Historial reciente</h2>
          <AlertsTable alerts={resolved} emptyText="Sin alertas resueltas todavía." />
        </div>

        <div>
          <div style={styles.card}>
            <h2 style={{ marginTop: 0 }}>Reglas</h2>
            <table style={styles.table}>
              <tbody>
                {(rules.data ?? []).map((r) => (
                  <tr key={r.id}>
                    <td style={styles.td}>
                      <span style={badge(SEVERITY_STYLE[r.severity])}>{r.severity}</span>
                    </td>
                    <td style={styles.td}>{r.name}</td>
                    <td style={styles.td}>
                      <label style={{ cursor: "pointer" }}>
                        <input
                          type="checkbox"
                          checked={r.enabled}
                          onChange={(e) => toggleRule.mutate({ id: r.id, enabled: e.target.checked })}
                        />{" "}
                        activa
                      </label>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={styles.card}>
            <h2 style={{ marginTop: 0 }}>Canales de notificación</h2>
            {(channels.data ?? []).length === 0 && (
              <p style={styles.dim}>Sin canales. Las alertas solo se verán en el NOC.</p>
            )}
            <ul style={{ listStyle: "none", padding: 0 }}>
              {(channels.data ?? []).map((c) => (
                <li key={c.id} style={{ marginBottom: "0.4rem" }}>
                  <span style={styles.mono}>{c.name}</span> <span style={styles.dim}>({c.channel_type})</span>{" "}
                  <button style={inputStyle} onClick={() => test.mutate(c.id)}>Probar</button>{" "}
                  <button style={inputStyle} onClick={() => removeChannel.mutate(c.id)}>Eliminar</button>
                </li>
              ))}
            </ul>
            {test.isSuccess && <p style={styles.ok}>Mensaje de prueba enviado.</p>}
            {test.isError && <p style={styles.bad}>{String(test.error)}</p>}

            <h3>Añadir canal</h3>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <input style={inputStyle} placeholder="Nombre" value={chName} onChange={(e) => setChName(e.target.value)} />
              <select style={inputStyle} value={chType} onChange={(e) => setChType(e.target.value as "webhook" | "ntfy")}>
                <option value="ntfy">ntfy</option>
                <option value="webhook">webhook</option>
              </select>
              <input
                style={{ ...inputStyle, minWidth: 220 }}
                placeholder={chType === "ntfy" ? "topic (p. ej. meshtastic-noc)" : "URL del webhook"}
                value={chTarget}
                onChange={(e) => setChTarget(e.target.value)}
              />
              <button
                style={inputStyle}
                disabled={!chName || !chTarget}
                onClick={() => {
                  addChannel.mutate({
                    name: chName,
                    channel_type: chType,
                    enabled: true,
                    config: chType === "ntfy" ? { topic: chTarget } : { url: chTarget },
                  });
                  setChName("");
                  setChTarget("");
                }}
              >
                Crear
              </button>
            </div>
            {addChannel.isError && <p style={styles.bad}>{String(addChannel.error)}</p>}
          </div>
        </div>
      </div>
    </div>
  );
}

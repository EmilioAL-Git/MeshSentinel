import { useState } from "react";

/** Transportes de red (tcp / http / mqtt): un único estado y un único bloque
 * de campos compartido por los dos asistentes de "+ Añadir gateway" (ADR 0032). */
export type NetType = "tcp" | "http" | "mqtt";

export interface NetState {
  host: string;
  port: string;
  username: string;
  password: string;
  tls: boolean;
  topic: string;
  psk: string;
  bbox: string; // "sur, oeste, norte, este" o vacío
}

export const DEFAULT_PORT: Record<NetType, string> = { tcp: "4403", http: "80", mqtt: "1883" };

export const emptyNet = (): NetState => ({
  host: "", port: DEFAULT_PORT.tcp, username: "", password: "", tls: false,
  topic: "msh/#", psk: "AQ==", bbox: "",
});

export const isNetType = (t: string): t is NetType => t === "tcp" || t === "http" || t === "mqtt";

function parseBbox(raw: string): number[] | null {
  const parts = raw.split(/[,;\s]+/).filter(Boolean).map(Number);
  return parts.length === 4 && parts.every((n) => Number.isFinite(n)) ? parts : null;
}

export function netReady(type: NetType, n: NetState): boolean {
  if (n.host.trim() === "") return false;
  if (type === "mqtt" && n.bbox.trim() !== "" && parseBbox(n.bbox) === null) return false;
  return true;
}

export function netParams(type: NetType, n: NetState): Record<string, unknown> {
  const port = Number(n.port) || Number(DEFAULT_PORT[type]);
  const base: Record<string, unknown> = { host: n.host.trim(), port };
  if (type !== "mqtt") return base;
  if (n.username) base.username = n.username;
  if (n.password) base.password = n.password;
  if (n.tls) base.tls = true;
  if (n.topic.trim()) base.topic = n.topic.trim();
  if (n.psk.trim()) base.psk = n.psk.trim();
  const bbox = parseBbox(n.bbox);
  if (bbox) base.geo_bbox = bbox;
  return base;
}

const HINT: Record<NetType, string> = {
  tcp: "El firmware solo admite un cliente TCP a la vez — cierra la app oficial si está conectada.",
  http: "API HTTP del firmware (WiFi). Sin el límite de un único cliente, pero el volcado inicial tarda ~40 s con 200 nodos.",
  mqtt: "Solo ingesta: escucha un broker y nunca transmite. Descifra los canales con la clave indicada (AQ== = clave por defecto de Meshtastic).",
};

export function NetFields({
  type, net, onChange,
}: { type: NetType; net: NetState; onChange: (next: NetState) => void }) {
  const [showPass, setShowPass] = useState(false);
  const set = (patch: Partial<NetState>) => onChange({ ...net, ...patch });
  return (
    <div style={{ marginBottom: "0.8rem", display: "flex", gap: "0.6rem", flexWrap: "wrap", alignItems: "center", fontSize: 12 }}>
      <label>
        {type === "mqtt" ? "Broker" : "Host"}{" "}
        <input
          className="input"
          style={{ width: 190, fontFamily: "var(--font-mono)" }}
          placeholder={type === "mqtt" ? "mqtt.meshtastic.org" : "192.168.1.50 o meshtastic.local"}
          value={net.host}
          onChange={(e) => set({ host: e.target.value })}
        />
      </label>
      <label>
        Puerto{" "}
        <input className="input" style={{ width: 80 }} type="number" value={net.port}
          onChange={(e) => set({ port: e.target.value })} />
      </label>
      {type === "mqtt" && (
        <>
          <label>
            Usuario{" "}
            <input className="input" style={{ width: 120 }} autoComplete="off" value={net.username}
              onChange={(e) => set({ username: e.target.value })} />
          </label>
          <label>
            Clave{" "}
            <input className="input" style={{ width: 120 }} autoComplete="new-password"
              type={showPass ? "text" : "password"} value={net.password}
              onChange={(e) => set({ password: e.target.value })} />
            <button type="button" className="btn" style={{ marginLeft: 4 }} onClick={() => setShowPass((v) => !v)}>
              {showPass ? "ocultar" : "ver"}
            </button>
          </label>
          <label>
            <input type="checkbox" checked={net.tls} onChange={(e) => set({ tls: e.target.checked })} /> TLS
          </label>
          <label>
            Tema{" "}
            <input className="input" style={{ width: 150, fontFamily: "var(--font-mono)" }} value={net.topic}
              onChange={(e) => set({ topic: e.target.value })} />
          </label>
          <label>
            PSK{" "}
            <input className="input" style={{ width: 150, fontFamily: "var(--font-mono)" }} value={net.psk}
              onChange={(e) => set({ psk: e.target.value })} />
          </label>
          <label title="Los nodos que reporten una posición fuera de esta caja se ignoran">
            Zona{" "}
            <input className="input" style={{ width: 300, fontFamily: "var(--font-mono)" }}
              placeholder="sur, oeste, norte, este (opcional)" value={net.bbox}
              onChange={(e) => set({ bbox: e.target.value })} />
          </label>
        </>
      )}
      <span style={{ color: "var(--text-faint)", flexBasis: "100%" }}>{HINT[type]}</span>
    </div>
  );
}

// ── Nodo virtual (ADR 0033) ───────────────────────────────────────────────

export interface VnState {
  enabled: boolean;
  port: string;
  allowAdmin: boolean;
}

export const emptyVn = (): VnState => ({ enabled: false, port: "4404", allowAdmin: false });

/** Lee la configuración guardada en connection_params de un gateway. */
export function vnFromParams(params: Record<string, unknown>): VnState {
  return {
    enabled: params.vn_enabled === true,
    port: String(params.vn_port ?? "4404"),
    allowAdmin: params.vn_allow_admin === true,
  };
}

/** Añade las claves vn_* a unos connection_params (nunca para MQTT: no hay nodo). */
export function withVn(
  params: Record<string, unknown>, type: string, vn: VnState,
): Record<string, unknown> {
  const out = { ...params };
  delete out.vn_enabled; delete out.vn_port; delete out.vn_allow_admin;
  if (type === "mqtt" || type === "simulated" || !vn.enabled) return out;
  out.vn_enabled = true;
  out.vn_port = Number(vn.port) || 4404;
  if (vn.allowAdmin) out.vn_allow_admin = true;
  return out;
}

export function vnValid(vn: VnState): boolean {
  const port = Number(vn.port);
  return !vn.enabled || (Number.isInteger(port) && port >= 1024 && port <= 65535);
}

export function VirtualNodeFields({ vn, onChange }: { vn: VnState; onChange: (next: VnState) => void }) {
  return (
    <div style={{ marginBottom: "0.8rem", fontSize: 12, display: "flex", gap: "0.8rem", flexWrap: "wrap", alignItems: "center" }}>
      <label title="Expone este nodo a la app móvil o al CLI de Meshtastic a través de la pasarela">
        <input type="checkbox" checked={vn.enabled} onChange={(e) => onChange({ ...vn, enabled: e.target.checked })} />{" "}
        Nodo virtual
      </label>
      {vn.enabled && (
        <>
          <label>
            Puerto{" "}
            <input className="input" style={{ width: 80 }} type="number" value={vn.port}
              onChange={(e) => onChange({ ...vn, port: e.target.value })} />
          </label>
          <label title="Permite que el cliente envíe mensajes de administración (cambiar la configuración del nodo). Déjalo apagado si no lo necesitas.">
            <input type="checkbox" checked={vn.allowAdmin} onChange={(e) => onChange({ ...vn, allowAdmin: e.target.checked })} />{" "}
            Permitir administración
          </label>
          <span style={{ color: "var(--text-faint)", flexBasis: "100%" }}>
            Los clientes (app móvil, CLI) se conectan a <span className="mono">este-equipo:{vn.port}</span> como si fuera el
            nodo. Sin contraseña: cualquiera en tu red que alcance el puerto puede usarlo.
          </span>
        </>
      )}
    </div>
  );
}

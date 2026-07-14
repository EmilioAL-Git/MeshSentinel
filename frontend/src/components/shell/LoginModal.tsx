import { useState, type CSSProperties, type FormEvent } from "react";
import { t } from "../../tokens";
import { useAuth } from "../../context/AuthContext";

const overlayStyle: CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(0, 0, 0, 0.5)",
  zIndex: 1000,
  display: "flex",
  justifyContent: "center",
  alignItems: "flex-start",
  paddingTop: "14vh",
};

const boxStyle: CSSProperties = {
  width: "min(360px, 92vw)",
  background: t.surface,
  border: `1px solid ${t.border}`,
  borderRadius: 8,
  boxShadow: "0 12px 40px rgba(0, 0, 0, 0.55)",
  overflow: "hidden",
};

/** Modal de login (v0.7 §14.5 estilo): se abre desde el botón "Iniciar
 * sesión" del shell o automáticamente ante un 401 (interceptor de
 * client.ts → AuthContext). Copy fijo pedido por el usuario: la
 * monitorización nunca requiere sesión. */
export function LoginModal() {
  const { loginModalOpen, closeLoginModal, doLogin } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!loginModalOpen) return null;

  const close = () => {
    setError(null);
    setPassword("");
    closeLoginModal();
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await doLogin(username, password);
      setUsername("");
      setPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message.replace(/^HTTP \d+: /, "") : "No se pudo iniciar sesión");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={overlayStyle} onMouseDown={close}>
      <div style={boxStyle} onMouseDown={(e) => e.stopPropagation()}>
        <div className="panel-head">
          <div className="panel-title">Iniciar sesión</div>
        </div>
        <form onSubmit={submit} style={{ padding: 16, display: "flex", flexDirection: "column", gap: 10 }}>
          <p style={{ margin: 0, fontSize: 12, color: t.textDim }}>
            No es necesario iniciar sesión para consultar la información del sistema. Solo hace falta para
            operaciones que modifican la red.
          </p>
          <input
            className="input"
            placeholder="Usuario"
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          <input
            className="input"
            placeholder="Contraseña"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && <div style={{ color: t.crit, fontSize: 12 }}>{error}</div>}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 4 }}>
            <button type="button" className="btn ghost" onClick={close}>
              Cancelar
            </button>
            <button type="submit" className="btn primary" disabled={busy || !username || !password}>
              {busy ? "Entrando…" : "Entrar"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

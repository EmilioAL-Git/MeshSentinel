import { useAuth } from "../../context/AuthContext";

/** Marcador de zona bloqueada: la vista/pestaña existe pero exige sesión. */
export function LockedNotice({ what }: { what: string }) {
  const { openLoginModal, isAuthenticated } = useAuth();
  if (isAuthenticated) {
    return (
      <div className="empty" style={{ padding: "1.5rem", textAlign: "center" }}>
        <div style={{ fontSize: 22 }}>🔒</div>
        <p>{what} requiere rol de gestor o administrador.</p>
      </div>
    );
  }
  return (
    <div className="empty" style={{ padding: "1.5rem", textAlign: "center" }}>
      <div style={{ fontSize: 22 }}>🔒</div>
      <p>{what} requiere iniciar sesión.</p>
      <button className="btn" onClick={openLoginModal}>Iniciar sesión</button>
    </div>
  );
}

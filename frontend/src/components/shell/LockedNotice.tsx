import { useAuth } from "../../context/AuthContext";

/** Marcador de zona bloqueada: la vista/pestaña existe pero exige sesión. */
export function LockedNotice({ what }: { what: string }) {
  const { openLoginModal } = useAuth();
  return (
    <div className="empty" style={{ padding: "1.5rem", textAlign: "center" }}>
      <div style={{ fontSize: 22 }}>🔒</div>
      <p>{what} requiere iniciar sesión.</p>
      <button className="btn" onClick={openLoginModal}>Iniciar sesión</button>
    </div>
  );
}

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createUser,
  deleteUser,
  fetchUsers,
  setUserEnabled,
  setUserPassword,
  updateUser,
  type AuthUserOut,
} from "../api/client";
import { toast } from "./shell/Toast";
import { t } from "../tokens";

/**
 * Gestión de usuarios (autenticación): sin RBAC — is_admin solo gatea ESTA
 * pantalla (crear/editar/activar-desactivar/cambiar contraseña de otros/
 * eliminar). Cualquier usuario autenticado, admin o no, puede hacer
 * exactamente las mismas operaciones sobre la red en el resto de la app.
 */
export function UsersView() {
  const queryClient = useQueryClient();
  const usersQuery = useQuery({ queryKey: ["auth", "users"], queryFn: fetchUsers });

  const [newUsername, setNewUsername] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newIsAdmin, setNewIsAdmin] = useState(false);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["auth"] });

  const createMutation = useMutation({
    mutationFn: () => createUser({ username: newUsername, display_name: newDisplayName, password: newPassword, is_admin: newIsAdmin }),
    onSuccess: () => {
      toast(`Usuario «${newUsername}» creado`);
      setNewUsername("");
      setNewDisplayName("");
      setNewPassword("");
      setNewIsAdmin(false);
      invalidate();
    },
    onError: (err) => toast(err instanceof Error ? err.message.replace(/^HTTP \d+: /, "") : "No se pudo crear el usuario", { kind: "error" }),
  });

  const users = usersQuery.data ?? [];

  return (
    <div className="legacy-chrome" style={{ padding: "0.9rem", display: "flex", flexDirection: "column", gap: "1.2rem" }}>
      <div>
        <h2>Nuevo usuario</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (newUsername && newDisplayName && newPassword) createMutation.mutate();
          }}
          style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 8 }}
        >
          <input placeholder="Usuario" value={newUsername} onChange={(e) => setNewUsername(e.target.value)} />
          <input placeholder="Nombre visible" value={newDisplayName} onChange={(e) => setNewDisplayName(e.target.value)} />
          <input
            placeholder="Contraseña (mín. 10 caracteres)"
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
          />
          <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: t.textDim }}>
            <input type="checkbox" checked={newIsAdmin} onChange={(e) => setNewIsAdmin(e.target.checked)} />
            Administrador
          </label>
          <button type="submit" className="btn primary" disabled={createMutation.isPending}>
            Crear
          </button>
        </form>
      </div>

      <div>
        <h2>Usuarios ({users.length})</h2>
        {usersQuery.isLoading ? (
          <div className="empty">Cargando…</div>
        ) : users.length === 0 ? (
          <div className="empty">Sin usuarios todavía — el primero que crees será administrador automáticamente.</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8, fontSize: 12.5 }}>
            <thead>
              <tr style={{ textAlign: "left", color: t.textDim, borderBottom: `1px solid ${t.border}` }}>
                <th style={{ padding: "4px 8px" }}>Usuario</th>
                <th style={{ padding: "4px 8px" }}>Nombre</th>
                <th style={{ padding: "4px 8px" }}>Admin</th>
                <th style={{ padding: "4px 8px" }}>Estado</th>
                <th style={{ padding: "4px 8px" }}>Último acceso</th>
                <th style={{ padding: "4px 8px" }}></th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <UserRow key={u.id} user={u} onChanged={invalidate} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function UserRow({ user, onChanged }: { user: AuthUserOut; onChanged: () => void }) {
  const [editingName, setEditingName] = useState(false);
  const [displayName, setDisplayName] = useState(user.display_name);
  const [settingPassword, setSettingPassword] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const enabledMutation = useMutation({
    mutationFn: () => setUserEnabled(user.id, !user.enabled),
    onSuccess: onChanged,
    onError: (err) => toast(err instanceof Error ? err.message : "No se pudo cambiar el estado", { kind: "error" }),
  });
  const adminMutation = useMutation({
    mutationFn: (isAdmin: boolean) => updateUser(user.id, { is_admin: isAdmin }),
    onSuccess: onChanged,
    onError: (err) => toast(err instanceof Error ? err.message : "No se pudo cambiar el privilegio", { kind: "error" }),
  });
  const renameMutation = useMutation({
    mutationFn: () => updateUser(user.id, { display_name: displayName }),
    onSuccess: () => {
      setEditingName(false);
      onChanged();
    },
    onError: (err) => toast(err instanceof Error ? err.message : "No se pudo renombrar", { kind: "error" }),
  });
  const passwordMutation = useMutation({
    mutationFn: () => setUserPassword(user.id, password),
    onSuccess: () => {
      toast(`Contraseña de «${user.username}» actualizada`);
      setSettingPassword(false);
      setPassword("");
    },
    onError: (err) => toast(err instanceof Error ? err.message.replace(/^HTTP \d+: /, "") : "No se pudo cambiar la contraseña", { kind: "error" }),
  });
  const deleteMutation = useMutation({
    mutationFn: () => deleteUser(user.id),
    onSuccess: () => {
      toast(`Usuario «${user.username}» eliminado`);
      onChanged();
    },
    onError: (err) => toast(err instanceof Error ? err.message : "No se pudo eliminar", { kind: "error" }),
  });

  return (
    <tr style={{ borderBottom: `1px solid ${t.borderSubtle}` }}>
      <td style={{ padding: "4px 8px", fontFamily: t.fontMono }}>{user.username}</td>
      <td style={{ padding: "4px 8px" }}>
        {editingName ? (
          <span style={{ display: "flex", gap: 4 }}>
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} style={{ width: 140 }} />
            <button className="btn" onClick={() => renameMutation.mutate()} disabled={renameMutation.isPending}>
              Guardar
            </button>
            <button className="btn ghost" onClick={() => setEditingName(false)}>
              Cancelar
            </button>
          </span>
        ) : (
          <span onClick={() => setEditingName(true)} style={{ cursor: "pointer" }} title="Editar nombre">
            {user.display_name}
          </span>
        )}
      </td>
      <td style={{ padding: "4px 8px" }}>
        <input type="checkbox" checked={user.is_admin} onChange={(e) => adminMutation.mutate(e.target.checked)} />
      </td>
      <td style={{ padding: "4px 8px", color: user.enabled ? t.ok : t.textFaint }}>
        {user.enabled ? "Activo" : "Deshabilitado"}
      </td>
      <td style={{ padding: "4px 8px", color: t.textDim }}>
        {user.last_login_at ? new Date(user.last_login_at).toLocaleString() : "—"}
      </td>
      <td style={{ padding: "4px 8px", whiteSpace: "nowrap" }}>
        <button className="btn ghost" onClick={() => enabledMutation.mutate()} disabled={enabledMutation.isPending}>
          {user.enabled ? "Desactivar" : "Activar"}
        </button>{" "}
        {settingPassword ? (
          <>
            <input
              type="password"
              placeholder="Nueva contraseña"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={{ width: 130 }}
            />
            <button className="btn" onClick={() => passwordMutation.mutate()} disabled={!password || passwordMutation.isPending}>
              Guardar
            </button>
            <button className="btn ghost" onClick={() => setSettingPassword(false)}>
              Cancelar
            </button>
          </>
        ) : (
          <button className="btn ghost" onClick={() => setSettingPassword(true)}>
            Contraseña…
          </button>
        )}{" "}
        {confirmingDelete ? (
          <button className="btn danger" onClick={() => deleteMutation.mutate()} disabled={deleteMutation.isPending}>
            ¿Seguro? Eliminar
          </button>
        ) : (
          <button className="btn ghost" onClick={() => setConfirmingDelete(true)}>
            Eliminar
          </button>
        )}
      </td>
    </tr>
  );
}

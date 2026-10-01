import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchMe, login as apiLogin, logout as apiLogout, onUnauthorized, type MeOut, type UserRole } from "../api/client";

/**
 * Sesión de MeshSentinel: monitorización siempre abierta (`protectedMode`
 * puede ser false para siempre si nunca se crea un administrador — cero
 * cambio de comportamiento). El interceptor 401 de client.ts llama a
 * `openLoginModal` desde aquí sin que ninguna de las ~40 mutaciones existentes
 * tenga que saber nada de autenticación.
 */

interface AuthContextValue {
  me: MeOut | null;
  isAuthenticated: boolean;
  isAdmin: boolean;
  /** Rol de la sesión (null sin sesión). */
  role: UserRole | null;
  /** Puede operar/editar la red: modo abierto, gestor o admin. El rol
   *  «usuario» y sin sesión en modo protegido ven solo lectura (el backend lo
   *  exige igualmente: RequireManagerDep). */
  canOperate: boolean;
  /** Ajustes de gateways y usuarios: modo abierto o admin. */
  canAdmin: boolean;
  /** Puede crear su Grupo del usuario y tener favoritos propios (cualquier cuenta). */
  hasPersonalSpace: boolean;
  protectedMode: boolean;
  loading: boolean;
  loginModalOpen: boolean;
  openLoginModal: () => void;
  closeLoginModal: () => void;
  doLogin: (username: string, password: string) => Promise<void>;
  doLogout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [loginModalOpen, setLoginModalOpen] = useState(false);

  const meQuery = useQuery({ queryKey: ["auth", "me"], queryFn: fetchMe });

  useEffect(() => {
    onUnauthorized(() => setLoginModalOpen(true));
    return () => onUnauthorized(null);
  }, []);

  const loginMutation = useMutation({
    mutationFn: (vars: { username: string; password: string }) => apiLogin(vars.username, vars.password),
    onSuccess: () => {
      setLoginModalOpen(false);
      queryClient.invalidateQueries(); // todo: los datos enmascarados cambian con la sesión
    },
  });

  const logoutMutation = useMutation({
    mutationFn: apiLogout,
    onSuccess: () => queryClient.invalidateQueries(),
  });

  const me = meQuery.data ?? null;
  const value: AuthContextValue = {
    me,
    isAuthenticated: me?.authenticated ?? false,
    isAdmin: me?.user?.is_admin ?? false,
    role: me?.user?.role ?? null,
    canOperate: !(me?.protected_mode ?? false) || (me?.user?.role === "admin" || me?.user?.role === "manager"),
    canAdmin: !(me?.protected_mode ?? false) || me?.user?.role === "admin",
    hasPersonalSpace: me?.authenticated ?? false,
    protectedMode: me?.protected_mode ?? false,
    loading: meQuery.isLoading,
    loginModalOpen,
    openLoginModal: () => setLoginModalOpen(true),
    closeLoginModal: () => setLoginModalOpen(false),
    doLogin: async (username, password) => {
      await loginMutation.mutateAsync({ username, password });
    },
    doLogout: async () => {
      await logoutMutation.mutateAsync();
    },
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth() requiere <AuthProvider> como ancestro");
  return ctx;
}

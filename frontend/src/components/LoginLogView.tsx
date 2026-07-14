import { useInfiniteQuery } from "@tanstack/react-query";
import { fetchLoginLog } from "../api/client";
import { t } from "../tokens";

const PAGE_SIZE = 100;

const EVENT_LABEL: Record<string, string> = {
  login_ok: "Login correcto",
  login_failed: "Login fallido",
  logout: "Cierre de sesión",
  session_expired: "Sesión expirada",
  user_disabled: "Usuario deshabilitado",
  rate_limited: "Bloqueado (rate limit)",
};

const EVENT_COLOR: Record<string, string> = {
  login_ok: t.ok,
  login_failed: t.crit,
  logout: t.textDim,
  session_expired: t.warn,
  user_disabled: t.crit,
  rate_limited: t.crit,
};

/** Auditoría de accesos (solo lectura, paginada) — auth_login_log. */
export function LoginLogView() {
  const query = useInfiniteQuery({
    queryKey: ["auth", "login-log"],
    queryFn: ({ pageParam }) => fetchLoginLog(PAGE_SIZE, pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => (last.length === PAGE_SIZE ? last[last.length - 1].id : undefined),
  });

  const entries = (query.data?.pages ?? []).flat();

  return (
    <div className="legacy-chrome" style={{ padding: "0.9rem" }}>
      <h2>Accesos ({entries.length})</h2>
      {query.isLoading ? (
        <div className="empty">Cargando…</div>
      ) : entries.length === 0 ? (
        <div className="empty">Sin accesos registrados todavía.</div>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8, fontSize: 12.5 }}>
          <thead>
            <tr style={{ textAlign: "left", color: t.textDim, borderBottom: `1px solid ${t.border}` }}>
              <th style={{ padding: "4px 8px" }}>Fecha</th>
              <th style={{ padding: "4px 8px" }}>Usuario</th>
              <th style={{ padding: "4px 8px" }}>Evento</th>
              <th style={{ padding: "4px 8px" }}>Motivo</th>
              <th style={{ padding: "4px 8px" }}>IP</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id} style={{ borderBottom: `1px solid ${t.borderSubtle}` }}>
                <td style={{ padding: "4px 8px", color: t.textDim, fontFamily: t.fontMono }}>
                  {e.created_at ? new Date(e.created_at).toLocaleString() : "—"}
                </td>
                <td style={{ padding: "4px 8px", fontFamily: t.fontMono }}>{e.username}</td>
                <td style={{ padding: "4px 8px", color: EVENT_COLOR[e.event] ?? t.text }}>
                  {EVENT_LABEL[e.event] ?? e.event}
                </td>
                <td style={{ padding: "4px 8px", color: t.textDim }}>{e.reason ?? "—"}</td>
                <td style={{ padding: "4px 8px", color: t.textDim, fontFamily: t.fontMono }}>{e.ip ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {query.hasNextPage && (
        <div style={{ marginTop: 10 }}>
          <button className="btn ghost" onClick={() => query.fetchNextPage()} disabled={query.isFetchingNextPage}>
            {query.isFetchingNextPage ? "Cargando…" : "Cargar más"}
          </button>
        </div>
      )}
    </div>
  );
}

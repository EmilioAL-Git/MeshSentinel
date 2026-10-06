import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createApiToken, fetchApiTokens, revokeApiToken } from "../api/client";
import { toast } from "./shell/Toast";
import { t } from "../tokens";

const fmtDate = (iso: string) => new Date(iso).toLocaleString();

/**
 * Tokens Bearer para integraciones (ADR 0035). Solo el administrador con
 * sesión los gestiona. El valor en claro se muestra UNA vez al crearlo; el
 * servidor solo guarda su hash. Un token nunca es admin ni tiene espacio personal.
 */
export function ApiTokensPanel() {
  const queryClient = useQueryClient();
  const tokens = useQuery({ queryKey: ["auth", "tokens"], queryFn: fetchApiTokens });
  const [name, setName] = useState("");
  const [role, setRole] = useState<"manager" | "user">("user");
  const [days, setDays] = useState<number | "">(90);
  const [fresh, setFresh] = useState<{ name: string; token: string } | null>(null);

  const create = useMutation({
    mutationFn: () => createApiToken({ name: name.trim(), role, expires_days: days === "" ? null : days }),
    onSuccess: (res) => {
      setFresh({ name: res.name, token: res.token });
      setName("");
      queryClient.invalidateQueries({ queryKey: ["auth", "tokens"] });
    },
    onError: (e) => toast(e instanceof Error ? e.message.replace(/^HTTP \d+: /, "") : "No se pudo crear", { kind: "error" }),
  });
  const revoke = useMutation({
    mutationFn: (id: number) => revokeApiToken(id),
    onSuccess: () => {
      toast("Token revocado");
      queryClient.invalidateQueries({ queryKey: ["auth", "tokens"] });
    },
  });

  return (
    <div>
      <h2>Tokens de API ({tokens.data?.length ?? 0})</h2>
      <div style={{ color: t.textDim, fontSize: 12.5, maxWidth: 680, marginTop: 4 }}>
        Para integraciones externas: se envían como <code style={{ fontFamily: t.fontMono }}>Authorization: Bearer msk_…</code>.
        «Gestor» puede actuar sobre la red; «Usuario» es solo lectura. Un token no es administrador ni tiene
        favoritos/grupo personal. La documentación de la API está en <code style={{ fontFamily: t.fontMono }}>/api/v1/docs</code>.
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) create.mutate();
        }}
        style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 8 }}
      >
        <input placeholder="Nombre (p. ej. grafana)" value={name} onChange={(e) => setName(e.target.value)} />
        <select value={role} onChange={(e) => setRole(e.target.value as "manager" | "user")}>
          <option value="user">Usuario (solo lectura)</option>
          <option value="manager">Gestor</option>
        </select>
        <input
          type="number"
          min={1}
          style={{ width: 110 }}
          placeholder="Caduca (días)"
          value={days}
          onChange={(e) => setDays(e.target.value === "" ? "" : Number(e.target.value))}
          title="Vacío = no caduca"
        />
        <button className="btn" type="submit" disabled={create.isPending || !name.trim()}>
          Crear token
        </button>
      </form>
      {fresh && (
        <div style={{ marginTop: 10, padding: "8px 10px", border: `1px solid ${t.warn}`, borderRadius: 4, fontSize: 12.5 }}>
          Token «{fresh.name}» — <strong>cópialo ahora, no se vuelve a mostrar</strong>:
          <div className="mono" style={{ marginTop: 4, wordBreak: "break-all", userSelect: "all" }}>{fresh.token}</div>
          <button className="btn ghost" style={{ marginTop: 6 }} onClick={() => setFresh(null)}>
            Ya lo he copiado
          </button>
        </div>
      )}
      {(tokens.data?.length ?? 0) > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8, fontSize: 12.5 }}>
          <tbody>
            {tokens.data!.map((tk) => (
              <tr key={tk.id} style={{ borderBottom: `1px solid ${t.borderSubtle}` }}>
                <td style={{ padding: "4px 8px" }}>{tk.name}</td>
                <td className="mono" style={{ padding: "4px 8px" }}>{tk.token_prefix}…</td>
                <td style={{ padding: "4px 8px" }}>{tk.role === "manager" ? "Gestor" : "Usuario"}</td>
                <td style={{ padding: "4px 8px", color: t.textDim }}>
                  {tk.last_used_at ? `usado ${fmtDate(tk.last_used_at)}` : "sin usar"}
                </td>
                <td style={{ padding: "4px 8px", color: t.textDim }}>
                  {tk.expires_at ? `caduca ${fmtDate(tk.expires_at)}` : "no caduca"}
                </td>
                <td style={{ padding: "4px 8px" }}>
                  <button className="btn ghost" onClick={() => revoke.mutate(tk.id)}>
                    Revocar
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

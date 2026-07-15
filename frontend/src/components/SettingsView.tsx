import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchSettings, patchSetting, resetSetting, type SettingOut } from "../api/client";
import { toast } from "./shell/Toast";
import { t } from "../tokens";

const CATEGORY_ORDER = ["network", "alerts", "admin", "activity"];

function fmt(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Math.round(value * 100) / 100);
}

/**
 * Panel "Ajustes": umbrales operacionales editables sin redeploy (backend
 * Settings + overrides en BD). Cero lógica por parámetro — el backend manda
 * categoría/etiqueta/unidad/mínimo, aquí solo se renderiza el control.
 */
export function SettingsView() {
  const queryClient = useQueryClient();
  const settingsQuery = useQuery({ queryKey: ["settings"], queryFn: fetchSettings });
  const settings = settingsQuery.data ?? [];

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["settings"] });

  const groups = CATEGORY_ORDER.map((cat) => ({
    category: cat,
    label: settings.find((s) => s.category === cat)?.category_label ?? cat,
    items: settings.filter((s) => s.category === cat),
  })).filter((g) => g.items.length > 0);

  return (
    <div className="legacy-chrome" style={{ padding: "0.9rem", display: "flex", flexDirection: "column", gap: "1.4rem" }}>
      <p style={{ color: t.textDim, fontSize: 12.5, maxWidth: 640 }}>
        Umbrales y temporizadores operacionales de MeshSentinel. Un ajuste sin tocar vale su valor de fábrica
        (variables de entorno del backend); al guardar aquí, el cambio se aplica de inmediato en todo el proceso,
        sin reiniciar.
      </p>
      {settingsQuery.isLoading ? (
        <div className="empty">Cargando…</div>
      ) : (
        groups.map((g) => (
          <div key={g.category}>
            <h2>{g.label}</h2>
            <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8, fontSize: 12.5 }}>
              <tbody>
                {g.items.map((s) => (
                  <SettingRow key={s.key} setting={s} onChanged={invalidate} />
                ))}
              </tbody>
            </table>
          </div>
        ))
      )}
    </div>
  );
}

function SettingRow({ setting, onChanged }: { setting: SettingOut; onChanged: () => void }) {
  const [draft, setDraft] = useState<string>(fmt(setting.value));
  const [editing, setEditing] = useState(false);

  const saveMutation = useMutation({
    mutationFn: (value: number) => patchSetting(setting.key, value),
    onSuccess: () => {
      toast(`${setting.label} actualizado`);
      setEditing(false);
      onChanged();
    },
    onError: (err) =>
      toast(err instanceof Error ? err.message.replace(/^HTTP \d+: /, "") : "No se pudo guardar", { kind: "error" }),
  });
  const resetMutation = useMutation({
    mutationFn: () => resetSetting(setting.key),
    onSuccess: () => {
      toast(`${setting.label} restablecido al valor de fábrica`);
      onChanged();
    },
    onError: (err) => toast(err instanceof Error ? err.message : "No se pudo restablecer", { kind: "error" }),
  });

  const save = () => {
    const parsed = Number(draft);
    if (Number.isNaN(parsed)) {
      toast("Valor no numérico", { kind: "error" });
      return;
    }
    saveMutation.mutate(setting.value_type === "int" ? Math.round(parsed) : parsed);
  };

  return (
    <tr style={{ borderBottom: `1px solid ${t.borderSubtle}` }}>
      <td style={{ padding: "6px 8px", minWidth: 220 }}>
        <div>{setting.label}</div>
        <div style={{ color: t.textFaint, fontSize: 11, marginTop: 2, maxWidth: 480 }}>{setting.description}</div>
      </td>
      <td style={{ padding: "6px 8px", whiteSpace: "nowrap" }}>
        {editing ? (
          <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
            <input
              type="number"
              step={setting.value_type === "int" ? 1 : "any"}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              style={{ width: 100 }}
              autoFocus
            />
            {setting.unit && <span style={{ color: t.textDim }}>{setting.unit}</span>}
            <button className="btn" onClick={save} disabled={saveMutation.isPending}>
              Guardar
            </button>
            <button
              className="btn ghost"
              onClick={() => {
                setDraft(fmt(setting.value));
                setEditing(false);
              }}
            >
              Cancelar
            </button>
          </span>
        ) : (
          <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
            <span
              onClick={() => setEditing(true)}
              style={{ cursor: "pointer", fontFamily: t.fontMono }}
              title="Editar"
            >
              {fmt(setting.value)}
              {setting.unit ? ` ${setting.unit}` : ""}
            </span>
            {setting.overridden && (
              <span className="chip" title={`Valor de fábrica: ${fmt(setting.default_value)}${setting.unit ? ` ${setting.unit}` : ""}`}>
                personalizado
              </span>
            )}
            <button className="btn ghost" onClick={() => setEditing(true)}>
              Editar
            </button>
            {setting.overridden && (
              <button className="btn ghost" onClick={() => resetMutation.mutate()} disabled={resetMutation.isPending}>
                Restablecer
              </button>
            )}
          </span>
        )}
      </td>
    </tr>
  );
}

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchBackups,
  fetchConfigExport,
  fetchDigestStatus,
  fetchRuntime,
  fetchSettings,
  runBackupNow,
  storedBackupUrl,
  fetchStorage,
  importConfig,
  pruneNow,
  sendDigestNow,
  patchSetting,
  resetSetting,
  wipeAllNodes,
  WIPE_NODES_CONFIRM,
  type ConfigImportOut,
  type SettingOut,
} from "../api/client";
import { NexusPanel } from "./nexus/NexusPanel";
import { UsersView } from "./UsersView";
import { LoginLogView } from "./LoginLogView";
import { toast } from "./shell/Toast";
import { t } from "../tokens";
import { useAuth } from "../context/AuthContext";
import { useUrlString } from "../hooks/useUrlState";
import { fetchGroups, fetchStartupGroup, setStartupGroup, type StartupGroup } from "../api/client";

const CATEGORY_ORDER = ["network", "alerts", "admin", "activity", "security"];

const TAB_LABEL: Record<string, string> = {
  general: "General",
  mantenimiento: "Configuración",
  datos: "Datos",
  nexus: "Nexus",
  users: "Usuarios",
  "login-log": "Accesos",
};

function fmt(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Math.round(value * 100) / 100);
}

/** Factor de conversión a horas para el input "Personalizado" — solo para unidades de duración. */
function hourFactor(setting: SettingOut): number | null {
  if (setting.unit === "s") return 3600;
  if (setting.unit === "min") return 60;
  return null;
}

function valueLabel(setting: SettingOut, value: number): string {
  const preset = setting.choices?.find(([, v]) => v === value)?.[0];
  if (preset) return preset;
  const factor = hourFactor(setting);
  if (factor) return `${fmt(value / factor)} h`;
  return `${fmt(value)}${setting.unit ? ` ${setting.unit}` : ""}`;
}

/**
 * Panel "Ajustes": umbrales operacionales editables sin redeploy (backend
 * Settings + overrides en BD). Cero lógica por parámetro — el backend manda
 * categoría/etiqueta/unidad/mínimo, aquí solo se renderiza el control.
 */
export function SettingsView() {
  const authState = useAuth();
  const queryClient = useQueryClient();
  const settingsQuery = useQuery({ queryKey: ["settings"], queryFn: fetchSettings });
  const settings = settingsQuery.data ?? [];

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["settings"] });

  const groups = CATEGORY_ORDER.map((cat) => ({
    category: cat,
    label: settings.find((s) => s.category === cat)?.category_label ?? cat,
    items: settings.filter((s) => s.category === cat),
  })).filter((g) => g.items.length > 0);

  const canManageUsers = authState.canAdmin;
  const tabs = [
    ...(authState.canOperate ? ["general"] : []),
    // Importar/exportar/borrar la BD: solo admin (ADR 0029).
    ...(authState.canAdmin ? ["mantenimiento", "datos"] : []),
    ...(authState.canOperate ? ["nexus"] : []),
    ...(canManageUsers ? ["users"] : []),
    ...(authState.isAuthenticated ? ["login-log"] : []),
  ];

  const [urlTab, setUrlTab] = useUrlString("settings.tab", null, { replace: true });
  const tab = urlTab != null && tabs.includes(urlTab) ? urlTab : tabs[0];

  return (
    <div className="legacy-chrome" style={{ padding: "0.9rem", display: "flex", flexDirection: "column", gap: "1.2rem" }}>
      <span style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {tabs.map((id) => (
          <button
            key={id}
            onClick={() => setUrlTab(id === tabs[0] ? null : id)}
            style={{
              background: tab === id ? t.accentTint : t.surface2,
              border: `1px solid ${tab === id ? t.accent : t.borderSubtle}`,
              color: tab === id ? t.text : t.textDim,
              fontSize: 12,
              fontWeight: tab === id ? 650 : 500,
              borderRadius: 5,
              padding: "0.4rem 0.75rem",
              cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            {TAB_LABEL[id]}
          </button>
        ))}
      </span>

      {tab === "general" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1.4rem" }}>
          <p style={{ color: t.textDim, fontSize: 12.5, maxWidth: 640 }}>
            Umbrales y temporizadores operacionales de MeshSentinel. Un ajuste sin tocar vale su valor de
            fábrica (variables de entorno del backend); al guardar aquí, el cambio se aplica de inmediato en
            todo el proceso, sin reiniciar.
          </p>
          <StartupGroupSetting />
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
      )}

      {tab === "mantenimiento" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1.4rem" }}>
          <ConfigPortability />
          <NodeDbMaintenance />
        </div>
      )}

      {tab === "datos" && authState.canAdmin && (
        <DataPanel
          retentionSettings={settings.filter((s) => s.category === "retention")}
          digestSettings={settings.filter((s) => s.category === "digest")}
          backupSettings={settings.filter((s) => s.category === "backup")}
          onChanged={invalidate}
        />
      )}

      {tab === "nexus" && <NexusPanel />}
      {tab === "users" && canManageUsers && <UsersView />}
      {tab === "login-log" && authState.isAuthenticated && <LoginLogView />}
    </div>
  );
}

/** Preferencia local de este navegador: grupo con el que arranca la sesión. */
function StartupGroupSetting() {
  const groups = useQuery({ queryKey: ["groups"], queryFn: fetchGroups });
  const queryClient = useQueryClient();
  const startup = useQuery({ queryKey: ["startup-group"], queryFn: fetchStartupGroup });
  const save = useMutation({
    mutationFn: (v: StartupGroup) => setStartupGroup(v),
    onSuccess: (r) => queryClient.setQueryData(["startup-group"], r),
    onError: (e) => toast(e instanceof Error ? e.message : "No se pudo guardar", { kind: "error" }),
  });
  const value: StartupGroup = startup.data?.value ?? "last";
  const selected = value === "last" || value === "none" ? value : String(value);
  return (
    <div>
      <h2>Arranque</h2>
      <label style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8, fontSize: 12.5 }}>
        <span>Grupo al arrancar</span>
        <select
          className="input"
          value={selected}
          onChange={(e) => {
            const v = e.target.value;
            save.mutate(v === "last" || v === "none" ? v : Number(v));
          }}
        >
          <option value="last">Recordar el último usado (por navegador)</option>
          <option value="none">Toda la red</option>
          {(groups.data ?? []).map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </select>
      </label>
      <p style={{ color: t.textDim, fontSize: 12, marginTop: 6 }}>
        Ajuste global de la aplicación: vale para todos los usuarios y navegadores. Un enlace con grupo explícito siempre tiene prioridad.
      </p>
    </div>
  );
}

function downloadJson(data: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function summarizeCounts(counts: Record<string, number>): string {
  const parts = Object.entries(counts).filter(([, n]) => n > 0);
  if (parts.length === 0) return "nada";
  return parts.map(([key, n]) => `${n} ${key.replace(/_/g, " ")}`).join(", ");
}

/** Exportar/importar la configuración PORTABLE de esta instalación (reglas de
 * alerta globales/por grupo, canales/integraciones, perfiles de
 * configuración, grupos/etiquetas, ajustes de Nexus) para clonarla en otra.
 * Deliberadamente fuera: gateways, nodos/NodeDB, historial — específicos de
 * esta instalación. Importar nunca sobrescribe: solo crea lo que falte por
 * nombre (pensado para sembrar una instalación nueva, no sincronizar dos ya
 * vivas). */
function ConfigPortability() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);

  const invalidateAll = () => {
    for (const key of ["groups", "tags", "alert-rules", "channels", "providers", "profiles", "settings"]) {
      queryClient.invalidateQueries({ queryKey: [key] });
    }
  };

  const exportMutation = useMutation({
    mutationFn: fetchConfigExport,
    onSuccess: (data) => {
      downloadJson(data, `meshsentinel-config-${new Date().toISOString().slice(0, 10)}.json`);
      toast("Configuración exportada");
    },
    onError: (err) =>
      toast(err instanceof Error ? err.message.replace(/^HTTP \d+: /, "") : "No se pudo exportar", { kind: "error" }),
  });

  const importMutation = useMutation({
    mutationFn: importConfig,
    onSuccess: (res: ConfigImportOut) => {
      toast(`Importado: ${summarizeCounts(res.created)} (omitido por ya existir: ${summarizeCounts(res.skipped_existing)})`);
      if (res.skipped_invalid.length > 0) {
        toast(res.skipped_invalid.join("; "), { kind: "error" });
      }
      invalidateAll();
    },
    onError: (err) =>
      toast(err instanceof Error ? err.message.replace(/^HTTP \d+: /, "") : "No se pudo importar", { kind: "error" }),
    onSettled: () => setImporting(false),
  });

  const onFileChosen = async (file: File) => {
    setImporting(true);
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      importMutation.mutate(parsed);
    } catch {
      toast("El archivo no es un JSON de configuración válido", { kind: "error" });
      setImporting(false);
    }
  };

  return (
    <div>
      <h2>Configuración portable</h2>
      <div style={{ color: t.textDim, fontSize: 12.5, maxWidth: 640, marginBottom: 10 }}>
        Exporta reglas de alerta (globales o por grupo), canales e integraciones de notificación,
        perfiles de configuración, grupos/etiquetas y ajustes de Nexus a un archivo, para clonarlos en
        otra instalación de MeshSentinel. NO incluye gateways, nodos ni historial — eso es propio de
        cada instalación. Importar nunca sobrescribe: solo añade lo que aún no exista (por nombre).
      </div>
      <span style={{ display: "inline-flex", gap: 8 }}>
        <button className="btn" onClick={() => exportMutation.mutate()} disabled={exportMutation.isPending}>
          Exportar configuración…
        </button>
        <button
          className="btn ghost"
          onClick={() => fileInputRef.current?.click()}
          disabled={importing || importMutation.isPending}
        >
          Importar configuración…
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/json"
          style={{ display: "none" }}
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) void onFileChosen(file);
          }}
        />
      </span>
    </div>
  );
}

/** Reinicio de fábrica de la NodeDB de esta instalación: borrado TOTAL de los
 * nodos descubiertos + todo su historial derivado (alertas, operaciones/
 * lotes de administración, operaciones Nexus, diario de actividad), sin
 * tocar configuración (gateways, grupos/tags, reglas globales o por grupo,
 * canales, perfiles). Confirmación por texto (mismo patrón que los SET
 * destructivos de M1.3): evita un borrado de un solo clic. */
function NodeDbMaintenance() {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [confirmText, setConfirmText] = useState("");

  const invalidateAll = () => {
    for (const key of ["nodes", "dashboard", "stats", "topology", "activity", "alerts", "alert-rules", "jobs"]) {
      queryClient.invalidateQueries({ queryKey: [key] });
    }
  };

  const wipeMutation = useMutation({
    mutationFn: wipeAllNodes,
    onSuccess: (res) => {
      toast(
        `Instalación reiniciada de fábrica: ${res.deleted} nodo${res.deleted === 1 ? "" : "s"}, ` +
          `${res.alerts_deleted} alerta${res.alerts_deleted === 1 ? "" : "s"}, ` +
          `${res.admin_operations_deleted} operacion${res.admin_operations_deleted === 1 ? "" : "es"} y ` +
          `${res.activity_log_deleted} entrada${res.activity_log_deleted === 1 ? "" : "s"} de diario eliminadas`,
      );
      setExpanded(false);
      setConfirmText("");
      invalidateAll();
    },
    onError: (err) =>
      toast(
        err instanceof Error ? err.message.replace(/^HTTP \d+: /, "") : "No se pudo reiniciar la instalación",
        { kind: "error" },
      ),
  });

  return (
    <div>
      <h2>Mantenimiento</h2>
      <div style={{ color: t.textDim, fontSize: 12.5, maxWidth: 640, marginBottom: 10 }}>
        Reinicia esta instalación como si fuera de fábrica: borra TODOS los nodos descubiertos (la
        NodeDB) junto con todo lo que dependía de ellos — posiciones, telemetría, vecinos, etiquetas,
        membresías de grupo, alertas, operaciones y lotes de administración, operaciones Nexus y el
        diario de actividad. Gateways, grupos/etiquetas (definiciones), reglas de alerta globales o
        por grupo, canales/integraciones y perfiles de configuración NO se tocan — la malla se
        redescubre sola con el próximo tráfico. Útil antes de exportar/clonar esta instalación a otra
        instancia. Acción irreversible.
      </div>
      {!expanded ? (
        <button className="btn danger" onClick={() => setExpanded(true)}>
          Reiniciar de fábrica (borrar todos los nodos)…
        </button>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, maxWidth: 360 }}>
          <label style={{ fontSize: 12, color: t.textDim }}>
            Escribe <code style={{ fontFamily: t.fontMono }}>{WIPE_NODES_CONFIRM}</code> para confirmar:
          </label>
          <input
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            autoFocus
            style={{ fontFamily: t.fontMono }}
          />
          <span style={{ display: "inline-flex", gap: 6 }}>
            <button
              className="btn danger"
              disabled={confirmText !== WIPE_NODES_CONFIRM || wipeMutation.isPending}
              onClick={() => wipeMutation.mutate()}
            >
              Borrar definitivamente
            </button>
            <button
              className="btn ghost"
              onClick={() => {
                setExpanded(false);
                setConfirmText("");
              }}
            >
              Cancelar
            </button>
          </span>
        </div>
      )}
    </div>
  );
}

const CUSTOM = "__custom__";

function SettingRow({ setting, onChanged }: { setting: SettingOut; onChanged: () => void }) {
  const factor = hourFactor(setting);
  const [draft, setDraft] = useState<string>(fmt(setting.value));
  const [hoursDraft, setHoursDraft] = useState<string>(factor ? fmt(setting.value / factor) : fmt(setting.value));
  const [customMode, setCustomMode] = useState(false);
  const [editing, setEditing] = useState(false);

  const startEdit = () => {
    const isPreset = setting.choices?.some(([, v]) => v === setting.value) ?? true;
    setCustomMode(!isPreset);
    setDraft(fmt(setting.value));
    setHoursDraft(factor ? fmt(setting.value / factor) : fmt(setting.value));
    setEditing(true);
  };

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
    const usingHours = customMode && factor != null;
    const parsed = usingHours ? Number(hoursDraft) * factor! : Number(draft);
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
            {setting.choices && (
              <select
                value={customMode ? CUSTOM : draft}
                onChange={(e) => {
                  if (e.target.value === CUSTOM) {
                    setCustomMode(true);
                  } else {
                    setCustomMode(false);
                    setDraft(e.target.value);
                  }
                }}
                autoFocus={!customMode}
              >
                {setting.choices.map(([label, value]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
                <option value={CUSTOM}>Personalizado…</option>
              </select>
            )}
            {(!setting.choices || customMode) && factor != null ? (
              <>
                <input
                  type="number"
                  step="any"
                  value={hoursDraft}
                  onChange={(e) => setHoursDraft(e.target.value)}
                  style={{ width: 90 }}
                  autoFocus={!setting.choices}
                />
                <span style={{ color: t.textDim }}>h</span>
              </>
            ) : !setting.choices || customMode ? (
              <>
                <input
                  type="number"
                  step={setting.value_type === "int" ? 1 : "any"}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  style={{ width: 100 }}
                  autoFocus
                />
                {setting.unit && <span style={{ color: t.textDim }}>{setting.unit}</span>}
              </>
            ) : null}
            <button className="btn" onClick={save} disabled={saveMutation.isPending}>
              Guardar
            </button>
            <button
              className="btn ghost"
              onClick={() => {
                setEditing(false);
              }}
            >
              Cancelar
            </button>
          </span>
        ) : (
          <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
            <span onClick={startEdit} style={{ cursor: "pointer", fontFamily: t.fontMono }} title="Editar">
              {valueLabel(setting, setting.value)}
            </span>
            {setting.overridden && (
              <span className="chip" title={`Valor de fábrica: ${valueLabel(setting, setting.default_value)}`}>
                personalizado
              </span>
            )}
            <button className="btn ghost" onClick={startEdit}>
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

// ── Datos: retención por tipo, almacenamiento y salud del proceso ──────────

function fmtBytes(n: number | null): string {
  if (n == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

function fmtDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString() : "—";
}

function fmtUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return [d ? `${d} d` : "", h ? `${h} h` : "", `${m} min`].filter(Boolean).join(" ");
}

const thStyle = { textAlign: "left", padding: "4px 8px", color: t.textDim, fontWeight: 500, fontSize: 11.5 } as const;
const tdStyle = { padding: "5px 8px", fontSize: 12.5 } as const;

function DataPanel({
  retentionSettings,
  digestSettings,
  backupSettings,
  onChanged,
}: {
  retentionSettings: SettingOut[];
  digestSettings: SettingOut[];
  backupSettings: SettingOut[];
  onChanged: () => void;
}) {
  const queryClient = useQueryClient();
  const storage = useQuery({ queryKey: ["storage"], queryFn: fetchStorage, refetchInterval: 30_000 });
  const runtime = useQuery({ queryKey: ["runtime"], queryFn: fetchRuntime, refetchInterval: 10_000 });

  const digestStatus = useQuery({ queryKey: ["digest-status"], queryFn: fetchDigestStatus });
  const digest = useMutation({
    mutationFn: sendDigestNow,
    onSuccess: (res) => {
      toast(`Resumen enviado a ${res.delivered} de ${res.providers} integraciones`);
      queryClient.invalidateQueries({ queryKey: ["digest-status"] });
    },
    onError: (err) =>
      toast(err instanceof Error ? err.message.replace(/^HTTP \d+: /, "") : "No se pudo enviar", { kind: "error" }),
  });

  const backups = useQuery({ queryKey: ["backups"], queryFn: fetchBackups, refetchInterval: 30_000 });
  const backupNow = useMutation({
    mutationFn: runBackupNow,
    onSuccess: (run) => {
      toast(run.error ? `La copia falló: ${run.error}` : `Copia guardada: ${run.file}`, run.error ? { kind: "error" } : undefined);
      queryClient.invalidateQueries({ queryKey: ["backups"] });
    },
    onError: (err) =>
      toast(err instanceof Error ? err.message.replace(/^HTTP \d+: /, "") : "No se pudo copiar", { kind: "error" }),
  });

  const prune = useMutation({
    mutationFn: pruneNow,
    onSuccess: (run) => {
      const total = Object.values(run.deleted).reduce((a, b) => a + b, 0);
      if (run.error) toast(`La poda falló: ${run.error}`, { kind: "error" });
      else toast(total ? `Poda aplicada: ${total.toLocaleString()} filas eliminadas` : "Nada que podar con los plazos actuales");
      queryClient.invalidateQueries({ queryKey: ["storage"] });
    },
    onError: (err) =>
      toast(err instanceof Error ? err.message.replace(/^HTTP \d+: /, "") : "No se pudo podar", { kind: "error" }),
  });

  const s = storage.data;
  const r = runtime.data;
  const lastRun = s?.last_run;
  const lastTotal = lastRun ? Object.values(lastRun.deleted).reduce((a, b) => a + b, 0) : 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.4rem" }}>
      <p style={{ color: t.textDim, fontSize: 12.5, maxWidth: 680 }}>
        Cuánto tiempo conserva MeshSentinel cada tipo de dato. Una tarea en segundo plano poda cada hora lo que
        supere su plazo (por lotes, sin bloquear la ingesta); «Siempre» desactiva la poda de ese tipo. Las alertas
        activas, las operaciones en curso y los favoritos nunca se podan. Los cambios se aplican de inmediato.
      </p>

      <div className="kpis">
        <div className="kpi">
          <div className="v">{fmtBytes(s?.total_bytes ?? null)}</div>
          <div className="k">Tamaño de la BD ({s?.engine ?? "…"})</div>
        </div>
        <div className="kpi">
          <div className="v">{s ? s.tables.reduce((a, x) => a + x.rows, 0).toLocaleString() : "—"}</div>
          <div className="k">Filas totales</div>
        </div>
        <div className="kpi">
          <div className="v">{lastRun ? `${lastTotal.toLocaleString()}` : "—"}</div>
          <div className="k">
            {lastRun
              ? `Última poda: ${new Date(lastRun.finished_at).toLocaleString()} (${lastRun.trigger === "manual" ? "manual" : "programada"}, ${lastRun.duration_seconds} s)`
              : "Aún no ha corrido ninguna poda"}
          </div>
        </div>
      </div>
      {lastRun?.error && <div style={{ color: t.crit, fontSize: 12.5 }}>Última poda con error: {lastRun.error}</div>}

      <div>
        <h2>Plazos de retención</h2>
        <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8, fontSize: 12.5 }}>
          <tbody>
            {retentionSettings.map((st) => (
              <SettingRow key={st.key} setting={st} onChanged={() => { onChanged(); queryClient.invalidateQueries({ queryKey: ["storage"] }); }} />
            ))}
          </tbody>
        </table>
        <div style={{ marginTop: 10 }}>
          <button className="btn" disabled={prune.isPending || s?.running} onClick={() => prune.mutate()}>
            {prune.isPending || s?.running ? "Podando…" : "Aplicar ahora"}
          </button>
        </div>
      </div>

      <div>
        <h2>Resumen periódico</h2>
        <div style={{ color: t.textDim, fontSize: 12.5, maxWidth: 640, marginTop: 4 }}>
          Mensaje con el estado de la red, nodos nuevos, alertas y récords, enviado a todas las integraciones de
          notificación habilitadas (Alertas → Integraciones).
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8, fontSize: 12.5 }}>
          <tbody>
            {digestSettings.map((st) => (
              <SettingRow key={st.key} setting={st} onChanged={onChanged} />
            ))}
          </tbody>
        </table>
        <div style={{ marginTop: 10, display: "flex", gap: 10, alignItems: "center" }}>
          <button className="btn" disabled={digest.isPending} onClick={() => digest.mutate()}>
            {digest.isPending ? "Enviando…" : "Enviar ahora"}
          </button>
          <span style={{ color: t.textFaint, fontSize: 12 }}>
            {digestStatus.data?.last_sent_at
              ? `Último envío: ${new Date(digestStatus.data.last_sent_at).toLocaleString()}`
              : "Aún no se ha enviado ninguno"}
          </span>
        </div>
      </div>

      <div>
        <h2>Copias automáticas</h2>
        <div style={{ color: t.textDim, fontSize: 12.5, maxWidth: 640, marginTop: 4 }}>
          Copia lógica completa guardada en el servidor (<code style={{ fontFamily: t.fontMono }}>{backups.data?.directory ?? "…"}</code>),
          con rotación. Si una copia falla se avisa a las integraciones de notificación. Contienen hashes de
          contraseña y tokens: trata el directorio como un secreto.
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8, fontSize: 12.5 }}>
          <tbody>
            {backupSettings.map((st) => (
              <SettingRow key={st.key} setting={st} onChanged={onChanged} />
            ))}
          </tbody>
        </table>
        <div style={{ marginTop: 10, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <button className="btn" disabled={backupNow.isPending || backups.data?.running} onClick={() => backupNow.mutate()}>
            {backupNow.isPending || backups.data?.running ? "Copiando…" : "Copiar ahora"}
          </button>
          {backups.data?.last_run?.error && (
            <span style={{ color: t.crit, fontSize: 12 }}>Última copia con error: {backups.data.last_run.error}</span>
          )}
        </div>
        {(backups.data?.files.length ?? 0) > 0 && (
          <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8 }}>
            <tbody>
              {backups.data!.files.map((f) => (
                <tr key={f.name} style={{ borderBottom: `1px solid ${t.borderSubtle}` }}>
                  <td style={{ ...tdStyle, fontFamily: t.fontMono }}>{f.name}</td>
                  <td style={{ ...tdStyle, textAlign: "right", fontFamily: t.fontMono }}>{fmtBytes(f.size_bytes)}</td>
                  <td style={tdStyle}>{fmtDate(f.created_at)}</td>
                  <td style={tdStyle}>
                    <a href={storedBackupUrl(f.name)} download>
                      ⤓
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div>
        <h2>Almacenamiento por tipo de dato</h2>
        <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${t.borderSubtle}` }}>
              <th style={thStyle}>Tipo</th>
              <th style={{ ...thStyle, textAlign: "right" }}>Filas</th>
              <th style={{ ...thStyle, textAlign: "right" }}>Tamaño</th>
              <th style={thStyle}>Dato más antiguo</th>
              <th style={thStyle}>Retención</th>
            </tr>
          </thead>
          <tbody>
            {(s?.policies ?? []).map((p) => (
              <tr key={p.key} style={{ borderBottom: `1px solid ${t.borderSubtle}` }}>
                <td style={tdStyle}>{p.label}</td>
                <td style={{ ...tdStyle, textAlign: "right", fontFamily: t.fontMono }}>{p.rows.toLocaleString()}</td>
                <td style={{ ...tdStyle, textAlign: "right", fontFamily: t.fontMono }}>{fmtBytes(p.bytes)}</td>
                <td style={tdStyle}>{fmtDate(p.oldest)}</td>
                <td style={{ ...tdStyle, color: p.days ? t.text : t.textDim }}>{p.days ? `${p.days} d` : "Siempre"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <details>
        <summary style={{ cursor: "pointer", color: t.textDim, fontSize: 12.5 }}>
          Todas las tablas ({s?.tables.length ?? 0})
        </summary>
        <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8 }}>
          <tbody>
            {(s?.tables ?? []).map((tb) => (
              <tr key={tb.table} style={{ borderBottom: `1px solid ${t.borderSubtle}` }}>
                <td style={tdStyle}>
                  {tb.label}
                  {tb.label !== tb.table && (
                    <span style={{ color: t.textFaint, fontFamily: t.fontMono, fontSize: 11, marginLeft: 6 }}>{tb.table}</span>
                  )}
                </td>
                <td style={{ ...tdStyle, textAlign: "right", fontFamily: t.fontMono }}>{tb.rows.toLocaleString()}</td>
                <td style={{ ...tdStyle, textAlign: "right", fontFamily: t.fontMono }}>{fmtBytes(tb.bytes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>

      <div>
        <h2>Copia de seguridad</h2>
        <div style={{ color: t.textDim, fontSize: 12.5, maxWidth: 640, margin: "4px 0 8px" }}>
          Descarga una copia lógica completa (JSON Lines comprimido, válida para SQLite y PostgreSQL). Contiene
          hashes de contraseña y tokens de integraciones: guárdala como un secreto. Se restaura sobre una BD vacía
          y migrada con{" "}
          <code style={{ fontFamily: t.fontMono }}>docker compose exec backend python -m noc.restore_backup /ruta/copia.jsonl.gz</code>.
          Con bases grandes la descarga puede tardar.
        </div>
        <a className="btn" href="/api/v1/maintenance/backup" download>
          ⤓ Descargar copia
        </a>
      </div>

      <div>
        <h2>Salud del proceso MeshSentinel</h2>
        <div className="kpis" style={{ marginTop: 8 }}>
          <div className="kpi">
            <div className="v">{r ? fmtUptime(r.uptime_seconds) : "—"}</div>
            <div className="k">En marcha</div>
          </div>
          <div className="kpi">
            <div className="v">{r?.ws_clients ?? "—"}</div>
            <div className="k">Pestañas conectadas{r?.ws_dropped_clients ? ` · ${r.ws_dropped_clients} expulsadas` : ""}</div>
          </div>
          <div className="kpi">
            <div className="v" style={{ color: r && r.activity_dropped > 0 ? t.warn : undefined }}>
              {r ? `${r.activity_queue_size}/${r.activity_queue_max}` : "—"}
            </div>
            <div className="k">Cola del Registro{r?.activity_dropped ? ` · ${r.activity_dropped} descartadas` : ""}</div>
          </div>
          <div className="kpi">
            <div className="v" style={{ color: r && r.event_loop_lag_ms > 100 ? t.warn : undefined }}>
              {r ? `${r.event_loop_lag_ms} ms` : "—"}
            </div>
            <div className="k">Latencia del bucle de eventos</div>
          </div>
        </div>
      </div>
    </div>
  );
}

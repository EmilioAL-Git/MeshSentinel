import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type CSSProperties } from "react";
import {
  compareProfile,
  createProfile,
  createProfileVersion,
  deleteProfile,
  displayName,
  fetchConfigSchema,
  fetchNodeConfig,
  fetchProfile,
  fetchProfileVersions,
  fetchProfiles,
  previewProfileSync,
  syncProfile,
  type ConfigSchemaOut,
  type ConfigSectionSchema,
  type NodeSummaryOut,
  type ProfileSections,
  type SyncPreviewOut,
} from "../api/client";
import { styles } from "../styles";
import { coerceValue, displayValue, FieldControl, readCurrentValue, RISK_STYLE } from "./ConfigEditor";

const input: CSSProperties = {
  background: "#0d1117",
  border: "1px solid #30363d",
  color: "#e6edf3",
  borderRadius: 6,
  padding: "0.3rem 0.5rem",
};
const btn: CSSProperties = { ...input, cursor: "pointer" };

const DIFF_COLOR: Record<string, string> = {
  equal: "#3fb950",
  different: "#e3b341",
  unknown: "#8b949e",
};
const DIFF_LABEL: Record<string, string> = {
  equal: "igual",
  different: "distinto",
  unknown: "sin datos",
};

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `hace ${Math.round(seconds)}s`;
  if (seconds < 3600) return `hace ${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `hace ${Math.round(seconds / 3600)}h`;
  return `hace ${Math.round(seconds / 86400)}d`;
}

function fmtSeconds(s: number): string {
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}m ${Math.round(s % 60)}s`;
  return `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m`;
}

/** Los perfiles gestionan config y module_config; owner es identidad por nodo. */
function profileSections(schema: ConfigSchemaOut): ConfigSectionSchema[] {
  return schema.sections.filter((s) => s.kind !== "owner");
}

function profileGroups(schema: ConfigSchemaOut): Record<string, string[]> {
  const valid = new Set(profileSections(schema).map((s) => s.name));
  const out: Record<string, string[]> = {};
  for (const [group, names] of Object.entries(schema.ui_groups)) {
    const filtered = names.filter((n) => valid.has(n));
    if (filtered.length > 0) out[group] = filtered;
  }
  return out;
}

/** sections (valores tipados) → edits (strings crudos para los controles) */
function sectionsToEdits(sections: ProfileSections): Record<string, Record<string, string>> {
  const edits: Record<string, Record<string, string>> = {};
  for (const [section, values] of Object.entries(sections)) {
    edits[section] = {};
    for (const [field, value] of Object.entries(values)) {
      edits[section][field] = typeof value === "boolean" ? String(value) : String(value ?? "");
    }
  }
  return edits;
}

// ── Editor de perfil (crear / nueva versión) — reutiliza el editor dinámico ──

function ProfileEditor({
  schema,
  summaries,
  mode,
  initialSections,
  onCancel,
  onSaved,
}: {
  schema: ConfigSchemaOut;
  summaries: NodeSummaryOut[];
  mode: { kind: "create" } | { kind: "version"; profileId: number; profileName: string };
  initialSections: ProfileSections;
  onCancel: () => void;
  onSaved: (profileId: number) => void;
}) {
  const queryClient = useQueryClient();
  const groups = useMemo(() => profileGroups(schema), [schema]);
  const sectionsByName = useMemo(() => {
    const m: Record<string, ConfigSectionSchema> = {};
    for (const s of profileSections(schema)) m[s.name] = s;
    return m;
  }, [schema]);

  const firstGroup = Object.keys(groups)[0] ?? "";
  const [activeGroup, setActiveGroup] = useState(firstGroup);
  const [activeSection, setActiveSection] = useState(groups[firstGroup]?.[0] ?? "");
  const [edits, setEdits] = useState<Record<string, Record<string, string>>>(() =>
    sectionsToEdits(initialSections),
  );
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [comment, setComment] = useState("");
  const [copyNodeId, setCopyNodeId] = useState("");

  // «Crear desde nodo»: precarga el editor con la última configuración conocida
  const copyFromNode = useMutation({
    mutationFn: (nodeId: string) => fetchNodeConfig(nodeId),
    onSuccess: (config) => {
      const next: Record<string, Record<string, string>> = {};
      for (const snap of config.sections) {
        const meta = sectionsByName[snap.section];
        if (!meta || snap.last_read_at == null) continue;
        for (const f of meta.fields) {
          if (!f.editable) continue;
          const value = readCurrentValue(snap.values, f.name);
          if (value === undefined || value === null || typeof value === "object") continue;
          (next[snap.section] ??= {})[f.name] = String(value);
        }
      }
      setEdits(next);
    },
  });

  const buildPayload = (): ProfileSections => {
    const payload: ProfileSections = {};
    for (const [sectionName, fields] of Object.entries(edits)) {
      const meta = sectionsByName[sectionName];
      if (!meta) continue;
      const values: Record<string, unknown> = {};
      for (const f of meta.fields) {
        const raw = fields[f.name];
        if (raw === undefined || raw === "") continue;
        values[f.name] = coerceValue(f, raw);
      }
      if (Object.keys(values).length > 0) payload[sectionName] = values;
    }
    return payload;
  };

  const payload = buildPayload();
  const managedCount = Object.values(payload).reduce((n, v) => n + Object.keys(v).length, 0);

  const save = useMutation({
    mutationFn: () =>
      mode.kind === "create"
        ? createProfile({ name, description: description || undefined, sections: payload }).then((p) => p.id)
        : createProfileVersion(mode.profileId, payload, comment || undefined).then(() => mode.profileId),
    onSuccess: (profileId) => {
      queryClient.invalidateQueries({ queryKey: ["profiles"] });
      queryClient.invalidateQueries({ queryKey: ["profile"] });
      queryClient.invalidateQueries({ queryKey: ["profile-versions"] });
      onSaved(profileId);
    },
  });

  const currentSection = sectionsByName[activeSection];
  const canSave = managedCount > 0 && (mode.kind === "version" || name.trim() !== "");

  return (
    <div style={styles.card}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.8rem", flexWrap: "wrap" }}>
        <h2 style={{ margin: 0 }}>
          {mode.kind === "create" ? "Nuevo perfil" : `Nueva versión de «${mode.profileName}»`}
        </h2>
        <button style={{ ...btn, marginLeft: "auto" }} onClick={onCancel}>✕ Cancelar</button>
      </div>

      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center", margin: "0.8rem 0" }}>
        {mode.kind === "create" ? (
          <>
            <input
              style={{ ...input, minWidth: 200 }}
              placeholder="Nombre del perfil *"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <input
              style={{ ...input, minWidth: 280 }}
              placeholder="Descripción (tipo de nodo que representa)"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </>
        ) : (
          <input
            style={{ ...input, minWidth: 280 }}
            placeholder="Comentario de la versión (qué cambia y por qué)"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
        )}
        <span style={{ display: "flex", gap: "0.4rem", alignItems: "center", marginLeft: "auto" }}>
          <select style={input} value={copyNodeId} onChange={(e) => setCopyNodeId(e.target.value)}>
            <option value="">— copiar desde nodo —</option>
            {summaries.map((s) => (
              <option key={s.node.node_id} value={s.node.node_id}>
                {displayName(s.node)}
              </option>
            ))}
          </select>
          <button
            style={btn}
            disabled={!copyNodeId || copyFromNode.isPending}
            onClick={() => copyFromNode.mutate(copyNodeId)}
            title="Rellena el perfil con la última configuración conocida del nodo"
          >
            Copiar
          </button>
        </span>
      </div>

      {/* Pestañas de grupos y secciones (mismo esquema que el editor M1.4) */}
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.5rem" }}>
        {Object.keys(groups).map((group) => (
          <button
            key={group}
            style={{ ...btn, background: activeGroup === group ? "#1f6feb" : "transparent" }}
            onClick={() => {
              setActiveGroup(group);
              const first = groups[group][0];
              if (first) setActiveSection(first);
            }}
          >
            {group}
          </button>
        ))}
      </div>
      <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap", marginBottom: "0.8rem" }}>
        {(groups[activeGroup] ?? []).map((sectionName) => {
          const s = sectionsByName[sectionName];
          if (!s) return null;
          const managed = Object.keys(payload[sectionName] ?? {}).length;
          return (
            <button
              key={sectionName}
              style={{
                ...btn,
                background: activeSection === sectionName ? "#30363d" : "transparent",
                borderColor: managed > 0 ? "#e3b341" : "#30363d",
                fontSize: "0.8rem",
              }}
              onClick={() => setActiveSection(sectionName)}
              title={s.description}
            >
              {s.display_name}
              {managed > 0 ? ` (${managed})` : ""}
            </button>
          );
        })}
      </div>

      {currentSection && (
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>Campo</th>
              <th style={styles.th}>Tipo</th>
              <th style={styles.th}>Valor del perfil</th>
            </tr>
          </thead>
          <tbody>
            {currentSection.fields.filter((f) => f.editable).map((f) => (
              <tr key={f.name}>
                <td style={{ ...styles.td, ...styles.mono }}>{f.name}</td>
                <td style={{ ...styles.td, ...styles.dim }}>{f.kind}</td>
                <td style={styles.td}>
                  <FieldControl
                    field={f}
                    currentValue={undefined}
                    editedRaw={edits[activeSection]?.[f.name]}
                    placeholder="— no gestionado —"
                    onChange={(raw) =>
                      setEdits((prev) => {
                        const sec = { ...(prev[activeSection] ?? {}) };
                        if (raw === "") delete sec[f.name];
                        else sec[f.name] = raw;
                        return { ...prev, [activeSection]: sec };
                      })
                    }
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div style={{ display: "flex", gap: "0.8rem", alignItems: "center", marginTop: "0.8rem" }}>
        <span style={styles.dim}>
          El perfil gestiona <strong>{managedCount}</strong> parámetros en{" "}
          <strong>{Object.keys(payload).length}</strong> secciones. Los campos vacíos no forman
          parte del perfil.
        </span>
        <button
          style={{ ...btn, marginLeft: "auto", background: canSave ? "#1f6feb" : "transparent" }}
          disabled={!canSave || save.isPending}
          onClick={() => save.mutate()}
        >
          {mode.kind === "create" ? "Crear perfil" : "Guardar como nueva versión"}
        </button>
      </div>
      {save.isError && <p style={styles.bad}>{String(save.error)}</p>}
      {copyFromNode.isError && <p style={styles.bad}>{String(copyFromNode.error)}</p>}
    </div>
  );
}

// ── Comparación perfil ↔ nodo ────────────────────────────────────────────────

function ComparePanel({
  profileId,
  versions,
  summaries,
}: {
  profileId: number;
  versions: number[];
  summaries: NodeSummaryOut[];
}) {
  const [nodeId, setNodeId] = useState("");
  const [version, setVersion] = useState<string>("");
  const [onlyDiffs, setOnlyDiffs] = useState(true);

  const compare = useQuery({
    queryKey: ["profile-compare", profileId, nodeId, version],
    queryFn: () => compareProfile(profileId, nodeId, version ? Number(version) : undefined),
    enabled: nodeId !== "",
    refetchInterval: 15_000,
  });

  const c = compare.data;
  return (
    <div style={{ border: "1px solid #30363d", borderRadius: 8, padding: "0.8rem", marginTop: "0.8rem" }}>
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
        <h3 style={{ margin: 0 }}>Comparar con nodo</h3>
        <select style={input} value={nodeId} onChange={(e) => setNodeId(e.target.value)}>
          <option value="">— nodo —</option>
          {summaries.map((s) => (
            <option key={s.node.node_id} value={s.node.node_id}>
              {displayName(s.node)} {s.node.online ? "· online" : "· offline"}
            </option>
          ))}
        </select>
        <select style={input} value={version} onChange={(e) => setVersion(e.target.value)}>
          <option value="">última versión</option>
          {versions.map((v) => (
            <option key={v} value={v}>v{v}</option>
          ))}
        </select>
        <label style={{ display: "flex", gap: "0.3rem", alignItems: "center", cursor: "pointer" }}>
          <input type="checkbox" checked={onlyDiffs} onChange={(e) => setOnlyDiffs(e.target.checked)} />
          solo diferencias
        </label>
      </div>

      {nodeId === "" && <p style={styles.dim}>Selecciona un nodo para ver las diferencias con el perfil.</p>}
      {compare.isError && <p style={styles.bad}>{String(compare.error)}</p>}
      {c && (
        <>
          <div style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap", margin: "0.6rem 0" }}>
            <span style={styles.ok}>Iguales: <strong>{c.equal_count}</strong></span>
            <span style={{ color: DIFF_COLOR.different }}>Distintos: <strong>{c.different_count}</strong></span>
            <span style={styles.dim}>Sin datos: <strong>{c.unknown_count}</strong></span>
            {c.different_count === 0 && c.unknown_count === 0 && (
              <span style={styles.ok}>✓ El nodo es conforme al perfil (v{c.version})</span>
            )}
          </div>
          {c.sections.map((sec) => {
            const rows = onlyDiffs ? sec.fields.filter((f) => f.status !== "equal") : sec.fields;
            if (rows.length === 0) return null;
            return (
              <div key={sec.section} style={{ marginBottom: "0.8rem" }}>
                <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                  <strong style={styles.mono}>{sec.section}</strong>
                  <span style={{ ...RISK_STYLE[sec.risk], borderRadius: 12, padding: "0 0.5rem", fontSize: "0.7rem" }}>
                    {sec.risk}
                  </span>
                  <span style={{ ...styles.dim, fontSize: "0.8rem" }}>
                    {sec.has_snapshot
                      ? `leído ${relativeTime(sec.last_read_at)}`
                      : "sin datos del nodo — refresca su configuración para comparar"}
                  </span>
                </div>
                <table style={styles.table}>
                  <thead>
                    <tr>
                      <th style={styles.th}>Campo</th>
                      <th style={styles.th}>Perfil</th>
                      <th style={styles.th}>Nodo</th>
                      <th style={styles.th}>Estado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((f) => (
                      <tr key={f.field}>
                        <td style={{ ...styles.td, ...styles.mono }}>{f.field}</td>
                        <td style={{ ...styles.td, ...styles.mono }}>{displayValue(f.profile_value)}</td>
                        <td style={{ ...styles.td, ...styles.mono }}>{displayValue(f.node_value)}</td>
                        <td style={styles.td}>
                          <span style={{ color: DIFF_COLOR[f.status], fontSize: "0.85rem" }}>
                            {DIFF_LABEL[f.status]}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}

// ── Sincronización (vía Batch Engine) ────────────────────────────────────────

function SyncPanel({
  profileId,
  profileName,
  versions,
  summaries,
  onOpenBatch,
}: {
  profileId: number;
  profileName: string;
  versions: number[];
  summaries: NodeSummaryOut[];
  onOpenBatch: (batchId: number) => void;
}) {
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [version, setVersion] = useState<string>("");
  const [includeUnknown, setIncludeUnknown] = useState(false);
  const [preview, setPreview] = useState<SyncPreviewOut | null>(null);
  const [confirmText, setConfirmText] = useState("");

  const body = () => ({
    node_ids: [...checked],
    version: version ? Number(version) : undefined,
    include_unknown: includeUnknown,
  });

  const doPreview = useMutation({
    mutationFn: () => previewProfileSync(profileId, body()),
    onSuccess: setPreview,
  });
  const doSync = useMutation({
    mutationFn: () => syncProfile(profileId, body()),
    onSuccess: (batch) => onOpenBatch(batch.id),
  });

  const toggle = (id: string) => {
    const next = new Set(checked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChecked(next);
    setPreview(null);
  };

  return (
    <div style={{ border: "1px solid #30363d", borderRadius: 8, padding: "0.8rem", marginTop: "0.8rem" }}>
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
        <h3 style={{ margin: 0 }}>Sincronizar nodos</h3>
        <select style={input} value={version} onChange={(e) => { setVersion(e.target.value); setPreview(null); }}>
          <option value="">última versión</option>
          {versions.map((v) => (
            <option key={v} value={v}>v{v}</option>
          ))}
        </select>
        <label style={{ display: "flex", gap: "0.3rem", alignItems: "center", cursor: "pointer" }} title="Las secciones nunca leídas no se pueden comparar. Con esta opción se escribe el perfil completo en ellas (el gateway fusiona sobre la lectura previa).">
          <input
            type="checkbox"
            checked={includeUnknown}
            onChange={(e) => { setIncludeUnknown(e.target.checked); setPreview(null); }}
          />
          incluir secciones sin datos
        </label>
        <span style={{ marginLeft: "auto", display: "flex", gap: "0.4rem" }}>
          <button
            style={btn}
            onClick={() => setChecked(new Set(summaries.filter((s) => s.node.online).map((s) => s.node.node_id)))}
          >
            + online
          </button>
          <button style={btn} onClick={() => { setChecked(new Set()); setPreview(null); }}>
            Limpiar
          </button>
        </span>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem", margin: "0.6rem 0", maxHeight: 160, overflowY: "auto" }}>
        {summaries.map((s) => (
          <label
            key={s.node.node_id}
            style={{
              display: "flex", gap: "0.3rem", alignItems: "center", cursor: "pointer",
              border: "1px solid " + (checked.has(s.node.node_id) ? "#1f6feb" : "#30363d"),
              borderRadius: 12, padding: "0.1rem 0.6rem", fontSize: "0.85rem",
            }}
          >
            <input
              type="checkbox"
              checked={checked.has(s.node.node_id)}
              onChange={() => toggle(s.node.node_id)}
            />
            <span style={s.node.online ? styles.ok : styles.bad}>●</span>
            {displayName(s.node)}
          </label>
        ))}
      </div>

      <button
        style={{ ...btn, background: checked.size > 0 ? "#1f6feb" : "transparent" }}
        disabled={checked.size === 0 || doPreview.isPending}
        onClick={() => doPreview.mutate()}
      >
        Simular sincronización ({checked.size} nodos)
      </button>
      {doPreview.isError && <p style={styles.bad}>{String(doPreview.error)}</p>}

      {preview && (
        <div style={{ marginTop: "0.8rem" }}>
          <div style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap" }}>
            <span>Perfil <strong>{preview.profile_name}</strong> v{preview.version}</span>
            <span style={styles.ok}>Nodos con cambios: <strong>{preview.eligible.length}</strong></span>
            <span style={styles.dim}>Sin cambios/excluidos: <strong>{preview.excluded.length}</strong></span>
            <span>Operaciones: <strong>{preview.total_operations}</strong></span>
            <span>Duración estimada: <strong>{fmtSeconds(preview.estimated_seconds)}</strong></span>
          </div>
          {preview.eligible.length > 0 && (
            <ul style={{ margin: "0.4rem 0" }}>
              {preview.eligible.map((p) => (
                <li key={p.node_id} style={{ fontSize: "0.9rem" }}>
                  <span style={styles.mono}>{p.display_name}</span> — {p.change_count} cambio
                  {p.change_count === 1 ? "" : "s"} en {Object.keys(p.sections_to_apply).join(", ")}
                  {p.warnings.length > 0 && (
                    <span style={{ color: "#d29922" }}> · {p.warnings.join("; ")}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {preview.excluded.length > 0 && (
            <ul style={{ margin: "0.4rem 0" }}>
              {preview.excluded.map((p) => (
                <li key={p.node_id} style={{ ...styles.dim, fontSize: "0.9rem" }}>
                  <span style={styles.mono}>{p.display_name}</span> — {p.blockers.join("; ")}
                </li>
              ))}
            </ul>
          )}
          {preview.eligible.length > 0 && (
            <>
              <p style={styles.dim}>
                Solo viajan los parámetros diferentes; cada sección se verifica con lectura
                posterior. Escribe <span style={styles.mono}>CONFIRMAR</span> para ejecutar:
              </p>
              <input style={input} value={confirmText} onChange={(e) => setConfirmText(e.target.value)} />
              <button
                style={{ ...btn, marginLeft: 8, background: confirmText === "CONFIRMAR" ? "#1f6feb" : "transparent" }}
                disabled={confirmText !== "CONFIRMAR" || doSync.isPending}
                onClick={() => doSync.mutate()}
              >
                Sincronizar ({preview.total_operations} operaciones)
              </button>
            </>
          )}
          {doSync.isError && <p style={styles.bad}>{String(doSync.error)}</p>}
        </div>
      )}
      <p style={{ ...styles.dim, fontSize: "0.8rem", marginBottom: 0 }}>
        La sincronización crea un batch estándar: se puede pausar, reanudar y seguir en la pestaña
        Batches. Perfil «{profileName}».
      </p>
    </div>
  );
}

// ── Detalle de un perfil ─────────────────────────────────────────────────────

function ProfileDetail({
  profileId,
  summaries,
  onBack,
  onNewVersion,
  onOpenBatch,
}: {
  profileId: number;
  summaries: NodeSummaryOut[];
  onBack: () => void;
  onNewVersion: (profileName: string, sections: ProfileSections) => void;
  onOpenBatch: (batchId: number) => void;
}) {
  const profile = useQuery({ queryKey: ["profile", profileId], queryFn: () => fetchProfile(profileId) });
  const versions = useQuery({
    queryKey: ["profile-versions", profileId],
    queryFn: () => fetchProfileVersions(profileId),
  });
  const [viewVersion, setViewVersion] = useState<number | null>(null);

  if (profile.isLoading || !profile.data) return <div style={styles.card}>Cargando perfil…</div>;
  const p = profile.data;
  const versionList = versions.data ?? [];
  const shown = viewVersion == null
    ? versionList.find((v) => v.version === p.latest_version)
    : versionList.find((v) => v.version === viewVersion);
  const shownSections = shown?.sections ?? p.sections;
  const versionNumbers = versionList.map((v) => v.version);

  return (
    <div>
      <div style={styles.card}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.8rem", flexWrap: "wrap" }}>
          <button style={btn} onClick={onBack}>← Perfiles</button>
          <h2 style={{ margin: 0 }}>{p.name}</h2>
          <span style={styles.dim}>v{p.latest_version}</span>
          {p.description && <span style={styles.dim}>{p.description}</span>}
          <button
            style={{ ...btn, marginLeft: "auto" }}
            onClick={() => onNewVersion(p.name, shownSections)}
            title={viewVersion != null && viewVersion !== p.latest_version
              ? `Parte de la v${viewVersion} (restaurar como nueva versión)`
              : "Editar el contenido creando una versión nueva"}
          >
            ✏️ {viewVersion != null && viewVersion !== p.latest_version
              ? `Restaurar v${viewVersion} como nueva versión`
              : "Editar (nueva versión)"}
          </button>
        </div>

        {/* Historial de versiones */}
        <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap", margin: "0.8rem 0" }}>
          {versionList.map((v) => (
            <button
              key={v.version}
              style={{
                ...btn,
                fontSize: "0.8rem",
                background: (viewVersion ?? p.latest_version) === v.version ? "#30363d" : "transparent",
              }}
              onClick={() => setViewVersion(v.version)}
              title={`${v.comment ?? "sin comentario"} · ${relativeTime(v.created_at)}`}
            >
              v{v.version}
              {v.version === p.latest_version ? " (actual)" : ""}
            </button>
          ))}
        </div>
        {shown && (
          <p style={{ ...styles.dim, fontSize: "0.85rem", margin: "0 0 0.5rem" }}>
            v{shown.version} · {shown.comment ?? "sin comentario"} · {relativeTime(shown.created_at)} · por {shown.created_by}
          </p>
        )}

        {/* Contenido de la versión mostrada */}
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>Sección</th>
              <th style={styles.th}>Campo</th>
              <th style={styles.th}>Valor</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(shownSections).flatMap(([section, values]) =>
              Object.entries(values).map(([field, value]) => (
                <tr key={`${section}.${field}`}>
                  <td style={{ ...styles.td, ...styles.mono }}>{section}</td>
                  <td style={{ ...styles.td, ...styles.mono }}>{field}</td>
                  <td style={{ ...styles.td, ...styles.mono }}>{displayValue(value)}</td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>

      <div style={styles.card}>
        <ComparePanel profileId={profileId} versions={versionNumbers} summaries={summaries} />
        <SyncPanel
          profileId={profileId}
          profileName={p.name}
          versions={versionNumbers}
          summaries={summaries}
          onOpenBatch={onOpenBatch}
        />
      </div>
    </div>
  );
}

// ── Vista principal ──────────────────────────────────────────────────────────

type EditorMode =
  | null
  | { kind: "create"; initial: ProfileSections }
  | { kind: "version"; profileId: number; profileName: string; initial: ProfileSections };

export function ProfilesView({
  summaries,
  onOpenBatch,
}: {
  summaries: NodeSummaryOut[];
  onOpenBatch: (batchId: number) => void;
}) {
  const queryClient = useQueryClient();
  const schema = useQuery({ queryKey: ["config-schema"], queryFn: fetchConfigSchema, staleTime: 3_600_000 });
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: fetchProfiles });
  const [openId, setOpenId] = useState<number | null>(null);
  const [editor, setEditor] = useState<EditorMode>(null);
  const [deleteArmed, setDeleteArmed] = useState<number | null>(null);

  const doDelete = useMutation({
    mutationFn: deleteProfile,
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["profiles"] });
      setDeleteArmed(null);
    },
  });

  if (schema.isLoading) return <div style={styles.card}>Cargando esquema…</div>;
  if (!schema.data) return <div style={styles.card}>No se pudo cargar el esquema.</div>;

  if (editor) {
    return (
      <ProfileEditor
        schema={schema.data}
        summaries={summaries}
        mode={editor.kind === "create"
          ? { kind: "create" }
          : { kind: "version", profileId: editor.profileId, profileName: editor.profileName }}
        initialSections={editor.initial}
        onCancel={() => setEditor(null)}
        onSaved={(profileId) => {
          setEditor(null);
          setOpenId(profileId);
        }}
      />
    );
  }

  if (openId != null) {
    return (
      <ProfileDetail
        profileId={openId}
        summaries={summaries}
        onBack={() => setOpenId(null)}
        onNewVersion={(profileName, sections) =>
          setEditor({ kind: "version", profileId: openId, profileName, initial: sections })
        }
        onOpenBatch={onOpenBatch}
      />
    );
  }

  const list = profiles.data ?? [];
  return (
    <div style={styles.card}>
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
        <h2 style={{ margin: 0 }}>Perfiles de configuración</h2>
        <button
          style={{ ...btn, marginLeft: "auto", background: "#1f6feb" }}
          onClick={() => setEditor({ kind: "create", initial: {} })}
        >
          + Nuevo perfil
        </button>
      </div>
      <p style={{ ...styles.dim, fontSize: "0.85rem" }}>
        Un perfil describe la configuración de un tipo de nodo (repetidor, sensor, móvil…). Se puede
        comparar contra cualquier nodo y sincronizar solo las diferencias mediante un batch.
      </p>
      {list.length === 0 && !profiles.isLoading && (
        <p style={styles.dim}>
          Sin perfiles todavía. Crea el primero desde cero o copiando la configuración de un nodo.
        </p>
      )}
      {list.length > 0 && (
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>Nombre</th>
              <th style={styles.th}>Descripción</th>
              <th style={styles.th}>Versión</th>
              <th style={styles.th}>Actualizado</th>
              <th style={styles.th}></th>
            </tr>
          </thead>
          <tbody>
            {list.map((p) => (
              <tr key={p.id} style={{ cursor: "pointer" }} onClick={() => setOpenId(p.id)}>
                <td style={styles.td}><strong>{p.name}</strong></td>
                <td style={{ ...styles.td, ...styles.dim }}>{p.description ?? ""}</td>
                <td style={styles.td}>v{p.latest_version}</td>
                <td style={styles.td}>{relativeTime(p.updated_at)}</td>
                <td style={styles.td}>
                  {deleteArmed === p.id ? (
                    <button
                      style={{ ...btn, background: "#b62324" }}
                      onClick={(e) => { e.stopPropagation(); doDelete.mutate(p.id); }}
                    >
                      ¿Eliminar «{p.name}» y sus versiones?
                    </button>
                  ) : (
                    <button
                      style={btn}
                      onClick={(e) => { e.stopPropagation(); setDeleteArmed(p.id); }}
                    >
                      Eliminar
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

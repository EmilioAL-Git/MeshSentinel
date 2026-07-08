import type { CSSProperties } from "react";
import type { GatewayOut, GroupOut, NodeFilterParams, TagOut } from "../api/client";
import { styles } from "../styles";

const input: CSSProperties = {
  background: "#0d1117",
  border: "1px solid #30363d",
  color: "#e6edf3",
  borderRadius: 6,
  padding: "0.3rem 0.5rem",
};

interface Props {
  filters: NodeFilterParams;
  onChange: (filters: NodeFilterParams) => void;
  tags: TagOut[];
  groups: GroupOut[];
  gateways: GatewayOut[];
  hwModels: string[];
}

/** Barra de búsqueda avanzada reutilizable (M1.2). */
export function NodeFiltersBar({ filters, onChange, tags, groups, gateways, hwModels }: Props) {
  const set = (patch: NodeFilterParams) => onChange({ ...filters, ...patch });
  const active = Object.values(filters).some((v) => v !== undefined && v !== "" && v !== false);

  return (
    <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center", marginBottom: "0.8rem" }}>
      <input
        style={{ ...input, minWidth: 180 }}
        placeholder="Buscar nombre o !id…"
        value={filters.q ?? ""}
        onChange={(e) => set({ q: e.target.value || undefined })}
      />
      <select style={input} value={filters.hw_model ?? ""} onChange={(e) => set({ hw_model: e.target.value || undefined })}>
        <option value="">hardware</option>
        {hwModels.map((h) => (
          <option key={h} value={h}>{h}</option>
        ))}
      </select>
      <select style={input} value={filters.tag ?? ""} onChange={(e) => set({ tag: e.target.value || undefined })}>
        <option value="">etiqueta</option>
        {tags.map((t) => (
          <option key={t.id} value={t.name}>{t.name}</option>
        ))}
      </select>
      <select
        style={input}
        value={filters.group_id ?? ""}
        onChange={(e) => set({ group_id: e.target.value ? Number(e.target.value) : undefined })}
      >
        <option value="">grupo</option>
        {groups.map((g) => (
          <option key={g.id} value={g.id}>
            {g.name} ({g.member_count})
          </option>
        ))}
      </select>
      <select style={input} value={filters.gateway_id ?? ""} onChange={(e) => set({ gateway_id: e.target.value || undefined })}>
        <option value="">pasarela</option>
        {gateways.map((g) => (
          <option key={g.gateway_id} value={g.gateway_id}>{g.gateway_id}</option>
        ))}
      </select>
      <select
        style={input}
        value={filters.online === undefined ? "" : String(filters.online)}
        onChange={(e) => set({ online: e.target.value === "" ? undefined : e.target.value === "true" })}
      >
        <option value="">estado</option>
        <option value="true">online</option>
        <option value="false">offline</option>
      </select>
      <label style={{ display: "flex", alignItems: "center", gap: 4 }}>
        <input
          type="checkbox"
          checked={filters.favorite === true}
          onChange={(e) => set({ favorite: e.target.checked ? true : undefined })}
        />
        ★ favoritos
      </label>
      <label style={{ display: "flex", alignItems: "center", gap: 4 }}>
        batería &lt;
        <input
          style={{ ...input, width: 55 }}
          type="number"
          min={1}
          max={101}
          value={filters.battery_below ?? ""}
          onChange={(e) => set({ battery_below: e.target.value ? Number(e.target.value) : undefined })}
        />
        %
      </label>
      <label style={{ display: "flex", alignItems: "center", gap: 4 }}>
        <input
          type="checkbox"
          checked={filters.include_ignored === true}
          onChange={(e) => set({ include_ignored: e.target.checked ? true : undefined })}
        />
        mostrar ignorados
      </label>
      {active && (
        <button style={{ ...input, cursor: "pointer" }} onClick={() => onChange({})}>
          Limpiar
        </button>
      )}
      <span style={{ ...styles.dim, fontSize: "0.8rem" }} />
    </div>
  );
}

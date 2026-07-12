import { type GatewaySelectionIn, type GatewayOut } from "../../api/client";

/**
 * Selección inteligente de gateway (Nivel 1 de la jerarquía): único selector
 * de todo MeshSentinel — usado por operaciones individuales, lotes y el
 * editor de configuración. Nunca tres implementaciones distintas.
 *
 * Codifica `GatewaySelectionIn` como un solo <select>: "auto" | "preferred"
 * | <gateway_id literal> — cada pasarela conocida es una opción "forzar
 * esta pasarela concreta" (Nivel 1, ADR de selección inteligente).
 */
export function GatewaySelect({
  value,
  onChange,
  gateways,
  compact,
}: {
  value: GatewaySelectionIn;
  onChange: (v: GatewaySelectionIn) => void;
  gateways: GatewayOut[];
  compact?: boolean;
}) {
  const current = value.mode === "forced" ? (value.gateway_id ?? "") : value.mode;
  const rows = gateways.filter((g) => g.enabled && g.deleted_at == null);

  return (
    <select
      className="input"
      style={compact ? { fontSize: 12 } : undefined}
      value={current}
      title="Gateway para esta operación: Automático (algoritmo M6.2) · Preferido (nodo/grupo, con reserva automática) · una pasarela concreta (forzada, sin reserva)"
      onChange={(e) => {
        const v = e.target.value;
        if (v === "auto" || v === "preferred") onChange({ mode: v });
        else onChange({ mode: "forced", gateway_id: v });
      }}
    >
      <option value="preferred">Preferido</option>
      <option value="auto">Automático</option>
      {rows.map((g) => (
        <option key={g.gateway_id} value={g.gateway_id}>
          {g.name ?? g.gateway_id}
        </option>
      ))}
    </select>
  );
}

/**
 * Editor de la preferencia en sí (Nivel 2 en el Inspector del nodo, Nivel 3
 * en el editor de grupo) — distinto de `GatewaySelect`: aquí no hay modo
 * "Preferido" (sería circular), solo "Automático" (sin preferencia, borra
 * `preferred_gateway_id`) o una pasarela concreta.
 */
export function PreferredGatewaySelect({
  value,
  onChange,
  gateways,
}: {
  value: string | null;
  onChange: (gatewayId: string | null) => void;
  gateways: GatewayOut[];
}) {
  const rows = gateways.filter((g) => g.enabled && g.deleted_at == null);
  return (
    <select
      className="input"
      style={{ fontSize: 12 }}
      value={value ?? ""}
      title="Gateway preferido: se usa siempre que esté operativo; si no, se avisa y se cae al automático"
      onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
    >
      <option value="">Automático</option>
      {rows.map((g) => (
        <option key={g.gateway_id} value={g.gateway_id}>
          {g.name ?? g.gateway_id}
        </option>
      ))}
    </select>
  );
}

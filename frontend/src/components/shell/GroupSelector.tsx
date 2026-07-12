import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { fetchGateways, setGroupPreferredGateway } from "../../api/client";
import { useActiveGroup } from "../../context/GroupContext";
import { t } from "../../tokens";
import { PreferredGatewaySelect } from "./GatewaySelect";

/**
 * Selector del grupo de trabajo activo: siempre visible en la cabecera, no
 * solo en Flota. "Toda la red" nunca queda escondido dentro del desplegable
 * — es la vía de escape de un clic al modo global. Cada fila incluye un
 * editor discreto del gateway preferido del grupo (Nivel 3 de la selección
 * inteligente) — este desplegable es la única superficie de "edición de
 * grupo" que existe hoy (no hay pantalla dedicada), así que es donde vive.
 */
export function GroupSelector() {
  const { activeGroupId, activeGroup, groups, setActiveGroup, clearActiveGroup } = useActiveGroup();
  const [open, setOpen] = useState(false);
  const [editingGroupId, setEditingGroupId] = useState<number | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();
  const gateways = useQuery({ queryKey: ["gateways"], queryFn: () => fetchGateways() });
  const setPreferred = useMutation({
    mutationFn: ({ groupId, gatewayId }: { groupId: number; gatewayId: string | null }) =>
      setGroupPreferredGateway(groupId, gatewayId),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["groups"] }),
  });

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
        setEditingGroupId(null);
      }
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, [open]);

  return (
    <div ref={rootRef} style={{ position: "relative", display: "flex", alignItems: "center", gap: "0.35rem" }}>
      <button
        className="btn ghost"
        onClick={() => setOpen((o) => !o)}
        title="Grupo de trabajo activo"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "0.4rem",
          border: `1px solid ${t.borderSubtle}`,
          whiteSpace: "nowrap",
        }}
      >
        <span style={{ color: t.textFaint, fontSize: 11 }}>GRUPO</span>
        <span>{activeGroup ? `${activeGroup.name} (${activeGroup.member_count})` : "Toda la red"}</span>
        <span style={{ color: t.textFaint, fontSize: 10 }}>▾</span>
      </button>
      <button
        className="btn ghost"
        onClick={clearActiveGroup}
        disabled={activeGroupId == null}
        title="Volver al modo global — todos los nodos"
        style={{
          border: `1px solid ${t.borderSubtle}`,
          opacity: activeGroupId == null ? 0.45 : 1,
          cursor: activeGroupId == null ? "default" : "pointer",
          whiteSpace: "nowrap",
        }}
      >
        Toda la red
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            zIndex: 970,
            minWidth: 260,
            background: t.surface,
            border: `1px solid ${t.border}`,
            borderRadius: 8,
            boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
            padding: "0.3rem",
            display: "flex",
            flexDirection: "column",
          }}
        >
          {groups.length === 0 && (
            <span style={{ padding: "0.4rem 0.5rem", color: t.textFaint, fontSize: 12 }}>
              Sin grupos todavía
            </span>
          )}
          {groups.map((g) => (
            <div key={g.id}>
              <div style={{ display: "flex", alignItems: "center" }}>
                <button
                  className="btn ghost"
                  onClick={() => {
                    setActiveGroup(g.id);
                    setOpen(false);
                  }}
                  style={{
                    flex: 1,
                    justifyContent: "space-between",
                    textAlign: "left",
                    background: g.id === activeGroupId ? t.accentTint : "none",
                    color: g.id === activeGroupId ? t.accent : t.text,
                  }}
                >
                  <span>{g.name}</span>
                  <span style={{ color: t.textFaint, fontSize: 11 }}>{g.member_count}</span>
                </button>
                <button
                  className="btn ghost"
                  title="Gateway preferido del grupo"
                  onClick={() => setEditingGroupId(editingGroupId === g.id ? null : g.id)}
                  style={{ padding: "0.2rem 0.4rem", color: g.preferred_gateway_id ? t.accent : t.textFaint }}
                >
                  ⚙
                </button>
              </div>
              {editingGroupId === g.id && (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.4rem",
                    padding: "0.3rem 0.5rem 0.4rem",
                  }}
                >
                  <span style={{ color: t.textFaint, fontSize: 10.5 }}>Gateway preferido</span>
                  <PreferredGatewaySelect
                    value={g.preferred_gateway_id}
                    onChange={(gatewayId) => setPreferred.mutate({ groupId: g.id, gatewayId })}
                    gateways={gateways.data ?? []}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

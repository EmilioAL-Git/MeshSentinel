import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchNexusOperationResponses, type NexusOperationOut, type NodeSummaryOut } from "../../api/client";
import { relativeTime } from "../../time";
import { chipStyle, t } from "../../tokens";
import { STATUS_COLORS, STATUS_LABELS } from "../nexus/NexusOperationsPanel";

const TARGET_LABEL: Record<string, string> = {
  broadcast: "Difusión",
  local: "Nodo local",
  group: "Grupo",
};

export function nexusTargetLabel(op: NexusOperationOut): string {
  return op.target_value ? `${op.target_kind}: ${op.target_value}` : (TARGET_LABEL[op.target_kind] ?? op.target_kind);
}

/** Fila de operación Nexus dentro del Centro de Trabajos (mismas secciones que el pipeline admin). */
export function NexusJobRow({
  op,
  summaries,
  flash,
  showTime,
  onOpenNode,
}: {
  op: NexusOperationOut;
  summaries: NodeSummaryOut[];
  flash: boolean;
  showTime: "created" | "finished";
  onOpenNode: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const multi = op.target_kind === "broadcast" || op.target_kind === "group";
  const node =
    op.target_kind === "node" && op.target_value
      ? summaries.find((s) => s.node.short_name === op.target_value)
      : undefined;
  const responses = useQuery({
    queryKey: ["nexus-op-responses", op.id],
    queryFn: () => fetchNexusOperationResponses(op.id),
    enabled: open && multi,
  });
  const color = STATUS_COLORS[op.status];

  return (
    <div className={flash ? "noc-flash" : undefined} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
      <div
        onClick={() => setOpen(!open)}
        title={`por ${op.created_by ?? "sistema"} · ${op.text}`}
        style={{ display: "flex", alignItems: "center", gap: 8, padding: "0.25rem 0.5rem", fontSize: 12, cursor: "pointer" }}
      >
        <span title="Operación Nexus">🐱</span>
        <span style={{ color: t.textFaint, fontFamily: t.fontMono, fontSize: 11 }}>#{op.id}</span>
        <span style={{ fontFamily: t.fontMono, color: t.text }}>
          {[op.command_name, ...op.args].join(" ")}
        </span>
        <span style={{ color: t.textDim, flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {node ? (
            <span
              onClick={(e) => {
                e.stopPropagation();
                onOpenNode(node.node.node_id);
              }}
              title="Abrir en el Inspector"
              style={{ cursor: "pointer" }}
            >
              {node.node.long_name ?? op.target_value}
            </span>
          ) : (
            nexusTargetLabel(op)
          )}
        </span>
        <span style={{ color: t.textFaint, fontFamily: t.fontMono, fontSize: 11 }}>{op.gateway_id}</span>
        <span style={{ ...chipStyle(color), fontSize: 10.5 }}>{STATUS_LABELS[op.status]}</span>
        <span style={{ color: t.textFaint, fontFamily: t.fontMono, fontSize: 11 }}>
          {relativeTime(showTime === "created" ? op.created_at : (op.response_at ?? op.sent_at ?? op.created_at))}
        </span>
      </div>
      {open && (
        <div style={{ padding: "0.2rem 0.75rem 0.5rem 2rem", fontSize: 11.5, color: t.textDim }}>
          <div style={{ fontFamily: t.fontMono }}>{op.text}</div>
          {multi ? (
            (responses.data ?? []).length === 0 ? (
              <div style={{ color: t.textFaint }}>{responses.isLoading ? "Cargando…" : "Sin respuestas todavía."}</div>
            ) : (
              (responses.data ?? []).map((r, i) => (
                <div key={r.id ?? i} style={{ fontFamily: t.fontMono }}>
                  {r.from_node_id}: {r.response_text}
                </div>
              ))
            )
          ) : (
            op.response_text && <pre style={{ margin: "4px 0 0", whiteSpace: "pre-wrap" }}>{op.response_text}</pre>
          )}
        </div>
      )}
    </div>
  );
}

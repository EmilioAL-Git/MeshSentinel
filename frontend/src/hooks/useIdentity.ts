import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchIdentity, type IdentityReportOut } from "../api/client";

/** Informe de identidad/claves (ADR 0034), compartido por toda la app con una
 * sola query: nunca llamar a fetchIdentity desde dentro de una fila de lista. */
export function useIdentityReport(): IdentityReportOut | undefined {
  return useQuery({ queryKey: ["identity"], queryFn: fetchIdentity, staleTime: 60_000, refetchInterval: 300_000 }).data;
}

/** node_id → texto de la insignia (⇄ cambio de identidad, ⚠ clave). Vacío si no hay nada. */
export function useIdentityBadges(): Map<string, string> {
  const report = useIdentityReport();
  return useMemo(() => {
    const m = new Map<string, string>();
    const add = (id: string, text: string) => m.set(id, m.has(id) ? `${m.get(id)} · ${text}` : text);
    for (const c of report?.changes ?? []) {
      add(c.predecessor_id, `⇄ Identidad antigua: sustituida por ${c.successor_id}`);
      add(c.successor_id, `⇄ Nueva identidad 2.8 (sustituye a ${c.predecessor_id})`);
    }
    for (const g of report?.duplicate_keys ?? []) for (const id of g.node_ids) add(id, "⚠ Clave duplicada con otro nodo");
    for (const w of report?.weak_keys ?? []) add(w.node_id, `⚠ Clave débil: ${w.reason}`);
    return m;
  }, [report]);
}

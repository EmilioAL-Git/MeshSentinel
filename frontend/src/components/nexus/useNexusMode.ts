import { useQuery } from "@tanstack/react-query";
import { fetchNexusMode } from "../../api/client";

/**
 * Estado del interruptor global JenTastic-Nexus (ADR 0027). Comparte caché
 * de TanStack Query (`["nexus-mode"]`) con NexusPanel — con el flag OFF (o
 * mientras carga) devuelve `false`, nunca `undefined`: cualquier insignia
 * u opción gateada por este hook se oculta por defecto, nunca aparece "un
 * instante" antes de resolver la petición.
 */
export function useNexusMode(): boolean {
  const query = useQuery({ queryKey: ["nexus-mode"], queryFn: fetchNexusMode, staleTime: 30_000 });
  return query.data?.enabled ?? false;
}

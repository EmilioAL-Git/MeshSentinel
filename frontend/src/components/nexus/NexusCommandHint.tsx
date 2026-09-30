import { useQuery } from "@tanstack/react-query";
import { fetchNexusCatalog } from "../../api/client";
import { t } from "../../tokens";

/**
 * Descripción de una línea para el comando tecleado, visible SIN tener que
 * abrir el explorador de catálogo (pedido explícito del usuario: "y en el
 * cuadro de operaciones Nexus?" — el ⓘ del explorador no ayuda si escribes
 * el comando a mano). Misma queryKey que NexusCatalogBrowser: comparten
 * caché, así que abrir el explorador después no vuelve a pedir el catálogo.
 */
export function NexusCommandHint({ command }: { command: string }) {
  const catalog = useQuery({ queryKey: ["nexus-catalog"], queryFn: fetchNexusCatalog });
  const normalized = command.trim().toUpperCase();
  if (!normalized) return null;
  const entry = catalog.data?.find((e) => e.name === normalized || e.aliases.includes(normalized));
  if (!entry) return null;
  return (
    <p style={{ color: t.textFaint, fontSize: 11, margin: "2px 0 0", maxWidth: 560 }}>
      <strong className="mono" style={{ color: t.textDim }}>{entry.name}</strong>: {entry.description || "sin descripción documentada"}
    </p>
  );
}

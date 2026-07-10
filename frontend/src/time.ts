/** Tiempo relativo compacto compartido (había 4 copias locales; usar esta). */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `hace ${Math.round(seconds)}s`;
  if (seconds < 3600) return `hace ${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `hace ${Math.round(seconds / 3600)}h`;
  return `hace ${Math.round(seconds / 86400)}d`;
}

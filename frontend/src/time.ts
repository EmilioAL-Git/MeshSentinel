/** Módulo ÚNICO de tiempo relativo (hardening): las copias locales que
 * vivían en AlertsView/ConfigEditor/GatewaysView/ProfilesView e
 * instruments.tsx se eliminaron — cualquier formato nuevo se añade AQUÍ. */

/** "hace 12s" / "hace 3m" / "hace 2h" / "hace 1d". */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return `hace ${fmtElapsed(Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000))}`;
}

/** Segundos transcurridos en compacto: "12s" / "3m" / "2h" / "1d". */
export function fmtElapsed(s: number): string {
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

/** Variante compacta de `relativeTime` sin el "hace" (columnas densas). */
export function relTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return fmtElapsed(Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000));
}

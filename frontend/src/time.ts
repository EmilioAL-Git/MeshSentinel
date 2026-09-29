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

/** Segundos transcurridos, con los DOS unidades más significativas:
 * "3 d 4 h" / "5 h 12 min" / "12 min" / "45 s". Para avisos y duraciones
 * largas donde un solo número en minutos (p.ej. "1334 min") es ilegible. */
export function fmtDuration(s: number): string {
  const total = Math.max(0, Math.round(s));
  if (total < 60) return `${total} s`;
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const mins = Math.floor((total % 3600) / 60);
  if (days > 0) return hours > 0 ? `${days} d ${hours} h` : `${days} d`;
  if (hours > 0) return mins > 0 ? `${hours} h ${mins} min` : `${hours} h`;
  return `${mins} min`;
}

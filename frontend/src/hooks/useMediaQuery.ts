import { useSyncExternalStore } from "react";

/** Suscripción a una media query CSS (cambia al girar el móvil / redimensionar). */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (notify) => {
      const mq = window.matchMedia(query);
      mq.addEventListener("change", notify);
      return () => mq.removeEventListener("change", notify);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

/**
 * Punto de corte "móvil" de toda la aplicación. DEBE coincidir con el
 * `@media` de mobile.css — es el único sitio donde se
 * decide qué es móvil (teléfono en vertical, tablets pequeñas y teléfono en horizontal).
 */
export const MOBILE_QUERY = "(max-width: 820px), (max-height: 500px) and (pointer: coarse)";

export function useIsMobile(): boolean {
  return useMediaQuery(MOBILE_QUERY);
}

/**
 * Sondeo adaptativo: mientras el canal en vivo (WebSocket) está conectado,
 * los eventos ya invalidan las queries (agrupados en ventanas de 2 s), así
 * que el `refetchInterval` es solo una red de seguridad y se espacia ×4.
 * Si el WS cae, vuelve al intervalo base. Las pestañas del navegador ocultas
 * ya no sondean (refetchIntervalInBackground=false por defecto en TanStack).
 *
 * Se usa en la forma de función de `refetchInterval`, que TanStack evalúa en
 * cada ciclo: no hace falta re-renderizar nada cuando cambia el estado.
 */
const RELAXED_FACTOR = 4;

let wsConnected = false;

export function setLiveConnected(connected: boolean): void {
  wsConnected = connected;
}

export const poll = (baseMs: number) => (): number => (wsConnected ? baseMs * RELAXED_FACTOR : baseMs);

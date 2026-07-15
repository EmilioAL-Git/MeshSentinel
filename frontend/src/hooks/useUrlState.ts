import { useCallback, useSyncExternalStore } from "react";

/**
 * URLs compartibles (ADR 0026, docs/design/urls-compartibles.md): store
 * mínimo sobre la History API nativa, mismo espíritu que usePersistedState
 * (hook pequeño y explícito, sin dependencia de router nueva). Todo cambio
 * de vista/parámetro pasa por aquí — ningún componente toca
 * `window.history` directamente.
 *
 * `replace` por defecto (afinar la vista actual); pasar `replace: false`
 * solo en navegaciones deliberadas (cambio de vista, abrir el Inspector) —
 * ver ADR 0026 "pushState en navegación deliberada".
 */

type Listener = () => void;
const listeners = new Set<Listener>();

function notify() {
  for (const l of listeners) l();
}

if (typeof window !== "undefined") {
  window.addEventListener("popstate", notify);
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSearchParams(): URLSearchParams {
  return new URLSearchParams(window.location.search);
}

function getSnapshot(): string {
  // useSyncExternalStore compara por referencia: exponemos el string crudo
  // (pathname+search) como snapshot, no un objeto reconstruido cada vez.
  return window.location.pathname + window.location.search;
}

function getServerSnapshot(): string {
  return "";
}

/** Suscripción cruda a "algo cambió en la URL" — base de los hooks tipados. */
function useUrlLocation(): string {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

interface SetOpts {
  /** true = replaceState (default), false = pushState (navegación real). */
  replace?: boolean;
}

function applyParam(key: string, value: string | null, opts: SetOpts) {
  const params = getSearchParams();
  if (value == null) params.delete(key);
  else params.set(key, value);
  const search = params.toString();
  const url = window.location.pathname + (search ? `?${search}` : "");
  if (opts.replace ?? true) window.history.replaceState(null, "", url);
  else window.history.pushState(null, "", url);
  notify();
}

/**
 * Parámetro de query genérico. `defaultValue` nunca se escribe en la URL
 * (§2 del diseño: "ningún parámetro se escribe si coincide con el
 * default") — se borra la clave en su lugar, para URLs cortas.
 */
export function useUrlParam<T>(
  key: string,
  defaultValue: T,
  opts: SetOpts & {
    parse: (raw: string) => T;
    serialize: (value: T) => string;
    isDefault?: (value: T) => boolean;
  },
): [T, (value: T, overrideOpts?: SetOpts) => void] {
  useUrlLocation();
  const raw = getSearchParams().get(key);
  const value = raw != null ? opts.parse(raw) : defaultValue;
  const isDefault = opts.isDefault ?? ((v: T) => v === defaultValue);
  const setValue = useCallback(
    (next: T, overrideOpts?: SetOpts) => {
      const serialized = isDefault(next) ? null : opts.serialize(next);
      applyParam(key, serialized, { replace: opts.replace ?? true, ...overrideOpts });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key],
  );
  return [value, setValue];
}

/** Parámetro de texto simple (caso más común: filtros, ids). */
export function useUrlString(
  key: string,
  defaultValue: string | null = null,
  opts: SetOpts = {},
): [string | null, (value: string | null, overrideOpts?: SetOpts) => void] {
  return useUrlParam<string | null>(key, defaultValue, {
    ...opts,
    parse: (raw) => raw,
    serialize: (v) => v ?? "",
    isDefault: (v) => v == null || v === defaultValue,
  });
}

/** Parámetro numérico (ids de grupo/lote/regla…). */
export function useUrlNumber(
  key: string,
  defaultValue: number | null = null,
  opts: SetOpts = {},
): [number | null, (value: number | null, overrideOpts?: SetOpts) => void] {
  return useUrlParam<number | null>(key, defaultValue, {
    ...opts,
    parse: (raw) => {
      const n = Number(raw);
      return Number.isFinite(n) ? n : defaultValue;
    },
    serialize: (v) => String(v),
    isDefault: (v) => v == null || v === defaultValue,
  });
}

/** Booleano: presencia de la clave = true, ausencia = false (§2 del diseño). */
export function useUrlFlag(key: string, opts: SetOpts = {}): [boolean, (value: boolean, overrideOpts?: SetOpts) => void] {
  return useUrlParam<boolean>(key, false, {
    ...opts,
    parse: () => true,
    serialize: () => "1",
    isDefault: (v) => v === false,
  });
}

/** Lista separada por comas (categorías, capas activas…). */
export function useUrlList(
  key: string,
  defaultValue: string[] = [],
  opts: SetOpts = {},
): [string[], (value: string[], overrideOpts?: SetOpts) => void] {
  const defaultSet = new Set(defaultValue);
  return useUrlParam<string[]>(key, defaultValue, {
    ...opts,
    parse: (raw) => (raw ? raw.split(",").filter(Boolean) : []),
    serialize: (v) => v.join(","),
    isDefault: (v) => v.length === defaultSet.size && v.every((x) => defaultSet.has(x)),
  });
}

/**
 * Vista activa (path, no query): caso especial porque vive en
 * `location.pathname`, no en `URLSearchParams`. `resolveView`/`View` se
 * inyectan desde quien los define (`frontend/src/view.ts`) para evitar
 * import circular con `App.tsx`.
 */
export function useUrlView<View extends string>(
  resolveView: (raw: string) => View,
  defaultView: View,
): [View, (view: View, overrideOpts?: SetOpts) => void] {
  useUrlLocation();
  const raw = window.location.pathname.replace(/^\//, "");
  const view = raw ? resolveView(raw) : defaultView;
  const setView = useCallback(
    (next: View, overrideOpts?: SetOpts) => {
      const search = window.location.search;
      const url = `/${next}${search}`;
      const replace = overrideOpts?.replace ?? false; // navegación real: pushState por defecto
      if (replace) window.history.replaceState(null, "", url);
      else window.history.pushState(null, "", url);
      notify();
    },
    [],
  );
  return [view, setView];
}

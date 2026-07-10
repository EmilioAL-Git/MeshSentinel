import { useEffect, useState } from "react";

/**
 * Estado de UI persistido en localStorage (v0.7 §3.2): anchos y plegados de
 * paneles, orden de bloques, modo del mapa… El operador configura su puesto
 * una vez y lo recupera en cada sesión. Base del sistema de paneles del
 * Centro de Operaciones (v0.7.1+).
 */
export function usePersistedState<T>(key: string, initial: T): [T, (value: T) => void] {
  const storageKey = `noc.${key}`;
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = window.localStorage.getItem(storageKey);
      return raw != null ? (JSON.parse(raw) as T) : initial;
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(value));
    } catch {
      // almacenamiento lleno o bloqueado: el estado sigue funcionando en memoria
    }
  }, [storageKey, value]);
  return [value, setValue];
}

import { type SetStateAction, useCallback, useSyncExternalStore } from "react";

/**
 * Estado de UI por vista (filtros, pestañas, selección, borradores) que sobrevive a la navegación:
 * vive fuera del árbol de React y se respalda en sessionStorage (sobrevive también a un F5).
 * Uso: const [tab, setTab] = useViewState("inventario.tab", "stock");
 */
const KEY = "arquifusion.view";
let store: Record<string, unknown> = (() => {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) ?? "{}") as Record<string, unknown>;
  } catch {
    return {};
  }
})();
const listeners = new Set<() => void>();
let saveTimer: ReturnType<typeof setTimeout> | null = null;

function persist() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try {
      sessionStorage.setItem(KEY, JSON.stringify(store));
    } catch {
      /* cuota o modo privado: el estado sigue en memoria */
    }
  }, 250);
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function useViewState<T>(key: string, initial: T): [T, (v: SetStateAction<T>) => void] {
  // Se registra el valor inicial una sola vez (idempotente): así el snapshot es estable entre renders.
  if (!(key in store)) store = { ...store, [key]: initial };
  const value = useSyncExternalStore(subscribe, () => store[key] as T);
  const setValue = useCallback(
    (v: SetStateAction<T>) => {
      const prev = (key in store ? store[key] : initial) as T;
      const next = typeof v === "function" ? (v as (p: T) => T)(prev) : v;
      if (Object.is(next, prev)) return;
      store = { ...store, [key]: next };
      persist();
      listeners.forEach((l) => l());
    },
    // `initial` solo se usa como valor por defecto; no debe recrear el setter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key],
  );
  return [value, setValue];
}

export function resetViewState() {
  store = {};
  persist();
  listeners.forEach((l) => l());
}

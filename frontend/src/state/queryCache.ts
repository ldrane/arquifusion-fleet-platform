import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";

/**
 * Caché de consultas a la API (stale-while-revalidate). Vive fuera de los componentes:
 * al volver a una vista, sus datos aparecen al instante y se revalidan en segundo plano.
 */
interface Entry<T = unknown> {
  data?: T;
  error?: unknown;
  loading: boolean;
  updatedAt: number;
}

const cache = new Map<string, Entry>();
const listeners = new Map<string, Set<() => void>>();
const inflight = new Map<string, Promise<unknown>>();
const EMPTY: Entry = { loading: false, updatedAt: 0 };

function emit(key: string) {
  listeners.get(key)?.forEach((l) => l());
}

function set(key: string, patch: Partial<Entry>) {
  cache.set(key, { ...(cache.get(key) ?? EMPTY), ...patch });
  emit(key);
}

export function fetchQuery<T>(key: string, fn: () => Promise<T>): Promise<T> {
  const running = inflight.get(key);
  if (running) return running as Promise<T>;
  set(key, { loading: true });
  const p = fn()
    .then((data) => {
      set(key, { data, error: undefined, loading: false, updatedAt: Date.now() });
      return data;
    })
    .catch((error) => {
      set(key, { error, loading: false });
      throw error;
    })
    .finally(() => inflight.delete(key));
  inflight.set(key, p);
  return p;
}

/** Invalida por prefijo (p. ej. tras un ack: "incident:" y "incidents"). */
export function invalidate(prefix: string) {
  for (const key of cache.keys()) {
    if (key.startsWith(prefix)) {
      const e = cache.get(key)!;
      cache.set(key, { ...e, updatedAt: 0 });
      emit(key);
    }
  }
}

export function clearQueries() {
  cache.clear();
  for (const key of listeners.keys()) emit(key);
}

export interface QueryResult<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  refetch: () => void;
}

/**
 * key = null desactiva la consulta (p. ej. el rol no tiene permiso).
 * staleMs: antigüedad a partir de la cual se revalida al montar. refreshMs: revalidación periódica.
 */
export function useQuery<T>(
  key: string | null,
  fn: () => Promise<T>,
  opts: { staleMs?: number; refreshMs?: number } = {},
): QueryResult<T> {
  const { staleMs = 15_000, refreshMs } = opts;
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const subscribe = useCallback(
    (l: () => void) => {
      if (!key) return () => {};
      if (!listeners.has(key)) listeners.set(key, new Set());
      listeners.get(key)!.add(l);
      return () => listeners.get(key)?.delete(l);
    },
    [key],
  );
  const entry = useSyncExternalStore(subscribe, () => (key ? (cache.get(key) ?? EMPTY) : EMPTY)) as Entry<T>;

  const refetch = useCallback(() => {
    if (key) fetchQuery(key, () => fnRef.current()).catch(() => {});
  }, [key]);

  useEffect(() => {
    if (!key) return;
    const e = cache.get(key);
    if (!e || Date.now() - e.updatedAt > staleMs) refetch();
  }, [key, staleMs, refetch, entry.updatedAt]);

  useEffect(() => {
    if (!key || !refreshMs) return;
    const t = setInterval(refetch, refreshMs);
    return () => clearInterval(t);
  }, [key, refreshMs, refetch]);

  return { data: entry.data, error: entry.error, loading: entry.loading && entry.data === undefined, refetch };
}

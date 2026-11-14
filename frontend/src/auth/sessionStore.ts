import type { Me } from "@/api/types";
import type { CognitoTokens } from "./cognito";

/**
 * Sesión en memoria + sessionStorage (se pierde al cerrar la pestaña; nunca localStorage para tokens).
 * Es un store externo mínimo: lo leen React (useSyncExternalStore) y el cliente HTTP.
 */
export interface Session {
  me: Me | null;
  tokens: CognitoTokens | null;
  name: string | null;
}

const KEY = "arquifusion.session";
let state: Session = load();
const listeners = new Set<() => void>();

function load(): Session {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as Session;
  } catch {
    /* sessionStorage no disponible */
  }
  return { me: null, tokens: null, name: null };
}

export const sessionStore = {
  get: () => state,
  set(next: Session) {
    state = next;
    try {
      if (next.me) sessionStorage.setItem(KEY, JSON.stringify(next));
      else sessionStorage.removeItem(KEY);
    } catch {
      /* ignorar */
    }
    listeners.forEach((l) => l());
  },
  clear() {
    sessionStore.set({ me: null, tokens: null, name: null });
  },
  subscribe(l: () => void) {
    listeners.add(l);
    return () => listeners.delete(l);
  },
};

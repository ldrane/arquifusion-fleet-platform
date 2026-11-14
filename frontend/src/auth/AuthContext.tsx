import { createContext, type ReactNode, useCallback, useContext, useMemo, useSyncExternalStore } from "react";
import type { Me, Role } from "@/api/types";
import { isDemo } from "@/config";
import { DEMO_USERS } from "@/demo/data";
import { api } from "@/services";
import { completeNewPassword, decodeJwt, login as cognitoLogin, type CognitoTokens } from "./cognito";
import { sessionStore } from "./sessionStore";

interface AuthValue {
  me: Me | null;
  name: string | null;
  role: Role | null;
  login(username: string, password: string): Promise<{ challenge?: { session: string; username: string } }>;
  completeChallenge(username: string, session: string, newPassword: string): Promise<void>;
  loginDemo(userId: string): void;
  logout(): void;
}

const Ctx = createContext<AuthValue | null>(null);

async function finish(tokens: CognitoTokens) {
  const claims = decodeJwt<Record<string, string>>(tokens.idToken);
  sessionStore.set({ me: null, tokens, name: claims.name ?? claims["cognito:username"] ?? null });
  // GET /me es la fuente del rol, la zona y el technician_id (api-lectura resuelve la precedencia de grupos)
  const me = await api.me();
  sessionStore.set({ me, tokens, name: claims.name ?? me.user_id });
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const session = useSyncExternalStore(sessionStore.subscribe, sessionStore.get);

  const login = useCallback(async (username: string, password: string) => {
    const r = await cognitoLogin(username.trim(), password);
    if (r.kind === "new_password") return { challenge: { session: r.session, username: r.username } };
    await finish(r.tokens);
    return {};
  }, []);

  const completeChallenge = useCallback(async (username: string, s: string, pwd: string) => {
    await finish(await completeNewPassword(username, s, pwd));
  }, []);

  const loginDemo = useCallback((userId: string) => {
    if (!isDemo) return;
    const u = DEMO_USERS.find((x) => x.user_id === userId);
    if (!u) return;
    sessionStore.set({ me: { user_id: u.user_id, email: u.email, role: u.role, zone: u.zone, technician_id: "technician_id" in u ? u.technician_id : null }, tokens: null, name: u.name });
  }, []);

  const logout = useCallback(() => sessionStore.clear(), []);

  const value = useMemo<AuthValue>(
    () => ({ me: session.me, name: session.name, role: session.me?.role ?? null, login, completeChallenge, loginDemo, logout }),
    [session, login, completeChallenge, loginDemo, logout],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth fuera de AuthProvider");
  return v;
}

/**
 * Composición de dependencias según el modo (config.ts):
 *   demo -> DemoWorld + DemoApi + DemoRealtime
 *   http -> HttpApi (Cognito) + FirestoreRealtime (o PollingRealtime si no hay Firebase)
 * Es lo único que sabe en qué modo corre la app.
 */
import type { FleetApi } from "./api/client";
import { HttpApi } from "./api/http";
import { refresh } from "./auth/cognito";
import { sessionStore } from "./auth/sessionStore";
import { config, hasFirebase, isDemo } from "./config";
import { DemoApi } from "./demo/demoApi";
import { DemoWorld } from "./demo/world";
import { DemoRealtime } from "./realtime/demo";
import { FirestoreRealtime } from "./realtime/firestore";
import { PollingRealtime } from "./realtime/polling";
import type { RealtimeSource } from "./realtime/types";

let refreshing: Promise<string | null> | null = null;

const tokenProvider = {
  async getIdToken(): Promise<string | null> {
    const { tokens } = sessionStore.get();
    if (!tokens) return null;
    if (tokens.expiresAt - Date.now() > 60_000) return tokens.idToken;
    if (!tokens.refreshToken) return tokens.idToken;
    refreshing ??= refresh(tokens.refreshToken)
      .then((t) => {
        sessionStore.set({ ...sessionStore.get(), tokens: t });
        return t.idToken;
      })
      .catch(() => {
        sessionStore.clear();
        return null;
      })
      .finally(() => (refreshing = null));
    return refreshing;
  },
  onUnauthorized() {
    sessionStore.clear();
  },
};

export const world: DemoWorld | null = isDemo ? new DemoWorld() : null;

export const api: FleetApi = world
  ? new DemoApi(world, () => sessionStore.get().me)
  : new HttpApi(config.apiUrl, tokenProvider);

export const realtime: RealtimeSource = world
  ? new DemoRealtime(world)
  : hasFirebase
    ? new FirestoreRealtime(api)
    : new PollingRealtime(api);

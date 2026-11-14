import { type FleetApi, fetchAll } from "@/api/client";
import type { Me } from "@/api/types";
import { can } from "@/auth/permissions";
import type { FleetUpdate, RealtimeSource } from "./types";

/** Respaldo sin Firebase: lee GET (API) cada `intervalMs`. El chat requiere Firestore. */
export class PollingRealtime implements RealtimeSource {
  readonly kind = "polling" as const;
  readonly canChat = false;

  constructor(
    private readonly api: FleetApi,
    private readonly intervalMs = 10_000,
  ) {}

  start(me: Me, onUpdate: (u: FleetUpdate) => void, onError: (e: unknown) => void) {
    let stopped = false;
    const load = async () => {
      try {
        const [machines, incidents, technicians] = await Promise.all([
          fetchAll((c) => this.api.listMachines({}, 100, c)),
          fetchAll((c) => this.api.listIncidents({}, 100, c)),
          can(me.role, "technicians") ? this.api.listTechnicians() : Promise.resolve(undefined),
        ]);
        if (!stopped) onUpdate({ machines, incidents, ...(technicians ? { technicians } : {}) });
      } catch (e) {
        if (!stopped) onError(e);
      }
    };
    void load();
    const t = setInterval(load, this.intervalMs);
    return () => {
      stopped = true;
      clearInterval(t);
    };
  }

  subscribeMessages(_id: string, onMessages: (m: never[]) => void) {
    onMessages([]);
    return () => {};
  }

  async sendMessage() {
    throw new Error("El chat necesita Firestore: falta VITE_FIREBASE_API_KEY y/o VITE_FIREBASE_PROJECT_ID (frontend/README.md)");
  }
}

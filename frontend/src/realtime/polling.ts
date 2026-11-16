import { type FleetApi, fetchAll } from "@/api/client";
import { ApiError } from "@/api/errors";
import type { Me } from "@/api/types";
import { can } from "@/auth/permissions";
import type { FleetUpdate, RealtimeSource } from "./types";

const RETRY_DELAYS_MS = [400, 1_200];

/** Throttling de Lambda vía API Gateway (429) y errores transitorios (5xx). */
function isRetryable(e: unknown): boolean {
  return e instanceof ApiError && (e.status === 429 || e.status >= 500);
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function withRetry<T>(fn: () => Promise<T>): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await fn();
    } catch (e) {
      if (!isRetryable(e) || attempt === RETRY_DELAYS_MS.length) throw e;
      await sleep(RETRY_DELAYS_MS[attempt]);
    }
  }
}

/** Respaldo sin Firebase: lee GET (API) cada `intervalMs`. El chat requiere Firestore. */
export class PollingRealtime implements RealtimeSource {
  readonly kind = "polling" as const;
  readonly canChat = false;

  constructor(
    private readonly api: FleetApi,
    private readonly intervalMs = 10_000, // REST (fallback sin Firestore): cuida la concurrencia de Lambda (AWS Academy)
  ) {}

  start(me: Me, onUpdate: (u: FleetUpdate) => void, onError: (e: unknown) => void) {
    let stopped = false;
    let running = false;
    const load = async () => {
      if (stopped || running) return; // un tick lento no se solapa con el siguiente
      running = true;
      try {
        // Secuencial a propósito: 3 GET concurrentes saturaban la concurrencia reservada de
        // api-lectura y Lambda los throttleaba (API Gateway responde 500 en AWS_PROXY).
        const machines = await withRetry(() => fetchAll((c) => this.api.listMachines({}, 100, c)));
        const incidents = await withRetry(() => fetchAll((c) => this.api.listIncidents({}, 100, c)));
        const technicians = can(me.role, "technicians")
          ? await withRetry(() => this.api.listTechnicians())
          : undefined;
        if (!stopped) onUpdate({ machines, incidents, ...(technicians ? { technicians } : {}) });
      } catch (e) {
        if (!stopped) onError(e);
      } finally {
        running = false;
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
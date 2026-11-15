/**
 * Tiempo real con Firestore (contratos.md §5, reglas en infra/gcp/firestore.rules).
 * 1. POST /auth/firebase-token -> custom token con claims role / zone / technician_id.
 * 2. signInWithCustomToken -> las Security Rules ven esos claims.
 * 3. onSnapshot sobre machines / incidents / technicians (filtrados por zona: las reglas exigen
 *    que la consulta no pueda devolver documentos de otra zona) y sobre el chat.
 * Caché persistente en IndexedDB: el chat se lee y se escribe sin conexión (RF-15, offline).
 * Push (RF-16): después de conectar se registra FCM (realtime/push.ts) y el token viaja en el body de
 * POST /auth/firebase-token (`fcm_token`), sin bloquear el arranque del tiempo real.
 * El SDK de Firebase se carga bajo demanda para no pesar en el modo demo.
 */
import type { FleetApi } from "@/api/client";
import type { ChatMessage, Incident, Machine, Me, Technician } from "@/api/types";
import { can } from "@/auth/permissions";
import { sessionStore } from "@/auth/sessionStore";
import { config } from "@/config";
import { myTechnicianId, newCorrelationId } from "@/lib/ids";
import { settleWrite } from "./chatPolicy";
import { registerPush } from "./push";
import type { FleetUpdate, RealtimeSource } from "./types";

type FirestoreMod = typeof import("firebase/firestore");
type Db = import("firebase/firestore").Firestore;

const strip = <T>(doc: Record<string, unknown>): T => {
  const { pk, sk, entity, ...rest } = doc;
  void [pk, sk, entity];
  return rest as T;
};

/** Timestamp de Firestore o string ISO -> ISO (replicar escribe ISO; serverTimestamp devuelve Timestamp). */
const toIso = (v: unknown): string => {
  if (!v) return new Date().toISOString();
  if (typeof v === "string") return v;
  if (typeof v === "object" && v && "toDate" in v) return (v as { toDate(): Date }).toDate().toISOString();
  return new Date().toISOString();
};

export class FirestoreRealtime implements RealtimeSource {
  readonly kind = "firestore" as const;
  readonly canChat = true;
  private ready: Promise<{ fs: FirestoreMod; db: Db; uid: string; role: string; techId: string | null }> | null = null;
  /** Usuario con el que se firmó `ready`: si cambia (logout → login con otro rol) hay que volver a firmar. */
  private readyFor: string | null = null;
  private me: Me | null = null;

  constructor(private readonly api: FleetApi) {}

  /** El chat puede montarse antes que el `start()` del FleetProvider (los efectos hijos corren primero):
   *  sin esto `subscribeMessages` quedaba en "Conectando al canal…" para siempre. */
  private currentMe(): Me | null {
    return this.me ?? sessionStore.get().me;
  }

  private connect(me: Me) {
    const key = `${me.user_id}|${me.role}|${me.zone ?? "*"}`;
    if (this.ready && this.readyFor === key) return this.ready;
    this.readyFor = key;
    this.ready = (async () => {
      const [{ initializeApp, getApps }, auth, fs] = await Promise.all([
        import("firebase/app"),
        import("firebase/auth"),
        import("firebase/firestore"),
      ]);
      const app =
        getApps()[0] ??
        initializeApp({
          apiKey: config.firebase.apiKey,
          authDomain: config.firebase.authDomain || `${config.firebase.projectId}.firebaseapp.com`,
          projectId: config.firebase.projectId,
          appId: config.firebase.appId || undefined,
        });
      let db: Db;
      try {
        db = fs.initializeFirestore(app, { localCache: fs.persistentLocalCache({ tabManager: fs.persistentMultipleTabManager() }) });
      } catch {
        db = fs.getFirestore(app); // ya inicializado (HMR) o IndexedDB no disponible
      }
      const { firebase_token } = await this.api.firebaseToken();
      const a = auth.getAuth(app);
      const cred = await auth.signInWithCustomToken(a, firebase_token);
      const claims = (await cred.user.getIdTokenResult()).claims;
      // Push en segundo plano: si hay token FCM, se registra con un segundo POST /auth/firebase-token.
      void registerPush(app)
        .then((fcmToken) => (fcmToken ? this.api.firebaseToken(fcmToken) : null))
        .catch(() => null);
      return {
        fs,
        db,
        uid: cred.user.uid,
        role: String(claims.role ?? me.role),
        techId: (claims.technician_id as string | null | undefined) ?? myTechnicianId(me),
      };
    })();
    const attempt = this.ready;
    attempt.catch(() => {
      if (this.ready === attempt) {
        this.ready = null;
        this.readyFor = null;
      }
    });
    return attempt;
  }

  start(me: Me, onUpdate: (u: FleetUpdate) => void, onError: (e: unknown) => void) {
    this.me = me;
    const unsubs: (() => void)[] = [];
    let stopped = false;
    this.connect(me)
      .then(({ fs, db, techId }) => {
        if (stopped) return;
        const { collection, query, where, onSnapshot } = fs;
        const zoned = (name: string, field: string) =>
          me.zone ? query(collection(db, name), where(field, "==", me.zone)) : collection(db, name);

        unsubs.push(
          onSnapshot(
            zoned("machines", "location.zone"),
            (s) => onUpdate({ machines: s.docs.map((d) => strip<Machine>(d.data())) }),
            onError,
          ),
          onSnapshot(
            zoned("incidents", "zone"),
            (s) => onUpdate({ incidents: s.docs.map((d) => strip<Incident>(d.data())) }),
            onError,
          ),
        );
        const techQuery = can(me.role, "technicians")
          ? zoned("technicians", "location.zone")
          : me.role === "tecnico" && techId
            ? query(collection(db, "technicians"), where("technician_id", "==", techId))
            : null;
        if (techQuery) {
          unsubs.push(
            onSnapshot(techQuery, (s) => onUpdate({ technicians: s.docs.map((d) => strip<Technician>(d.data())) }), onError),
          );
        }
      })
      .catch(onError);
    return () => {
      stopped = true;
      unsubs.forEach((u) => u());
    };
  }

  subscribeMessages(incidentId: string, onMessages: (m: ChatMessage[]) => void, onError: (e: unknown) => void) {
    const me = this.currentMe();
    if (!me) {
      onError(new Error("Sin sesión: no se puede abrir el chat"));
      return () => {};
    }
    let unsub = () => {};
    let stopped = false;
    this.connect(me)
      .then(({ fs, db }) => {
        if (stopped) return;
        const q = fs.query(fs.collection(db, "incidents", incidentId, "messages"), fs.orderBy("created_at", "asc"));
        unsub = fs.onSnapshot(
          q,
          { includeMetadataChanges: true },
          (s) =>
            onMessages(
              s.docs.map((d) => {
                const x = d.data({ serverTimestamps: "estimate" });
                return {
                  id: d.id,
                  author_id: String(x.author_id ?? ""),
                  role: x.role,
                  text: String(x.text ?? ""),
                  quick_action: x.quick_action ?? null,
                  attachment_path: x.attachment_path ?? null,
                  created_at: toIso(x.created_at),
                  correlation_id: String(x.correlation_id ?? ""),
                  pending: d.metadata.hasPendingWrites,
                } satisfies ChatMessage;
              }),
            ),
          onError,
        );
      })
      .catch(onError);
    return () => {
      stopped = true;
      unsub();
    };
  }

  async sendMessage(incidentId: string, text: string, quickAction?: string | null, onAsyncError?: (e: unknown) => void) {
    const me = this.currentMe();
    if (!me) throw new Error("Sin sesión");
    const { fs, db, uid, role } = await this.connect(me);
    // Campos exactos que valida firestore.rules (validMessage): created_at == request.time
    const doc: Record<string, unknown> = {
      author_id: uid,
      role,
      text,
      created_at: fs.serverTimestamp(),
      correlation_id: newCorrelationId(),
    };
    if (quickAction) doc.quick_action = quickAction;
    // Con red se espera la confirmación (un rechazo de las Security Rules llega al usuario como error);
    // sin red el SDK lo deja en cola en IndexedDB y se envía al reconectar.
    await settleWrite(fs.addDoc(fs.collection(db, "incidents", incidentId, "messages"), doc), {
      online: typeof navigator === "undefined" || navigator.onLine,
      onLateError: (e) => { console.warn("[chat] mensaje rechazado por Firestore", e); onAsyncError?.(e); },
    });
  }
}

import type { ChatMessage, Incident, Machine, Me, Technician } from "@/api/types";
import type { Notification } from "@/demo/world";

/** Actualización parcial de la flota: cada colección llega completa cuando cambia (como un onSnapshot). */
export interface FleetUpdate {
  machines?: Machine[];
  incidents?: Incident[];
  technicians?: Technician[];
}

/**
 * Fuente de tiempo real (contratos.md §5). Implementaciones:
 *  - firestore: onSnapshot de machines / incidents / technicians y chat (offline con caché persistente)
 *  - polling:   GET (API) cada 10 s cuando no hay config de Firebase (sin chat)
 *  - demo:      eventos del mundo simulado
 */
export interface RealtimeSource {
  readonly kind: "firestore" | "polling" | "demo";
  readonly canChat: boolean;
  start(me: Me, onUpdate: (u: FleetUpdate) => void, onError: (e: unknown) => void): () => void;
  subscribeMessages(incidentId: string, onMessages: (m: ChatMessage[]) => void, onError: (e: unknown) => void): () => void;
  /**
   * La promesa resuelve cuando el mensaje queda encolado (con caché offline no espera al servidor).
   * `onAsyncError` recibe el rechazo posterior del servidor (p. ej. permission-denied de las Security Rules).
   */
  sendMessage(incidentId: string, text: string, quickAction?: string | null, onAsyncError?: (e: unknown) => void): Promise<void>;
  /** Solo demo: avisos de eventos que no tienen colección en Firestore (repuestos, modelo). */
  subscribeNotifications?(onNotifications: (n: Notification[]) => void): () => void;
}

import { useEffect, useRef, useState } from "react";
import { errorMessage } from "@/api/errors";
import type { ChatMessage, Incident } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { DEMO_USERS, SEED } from "@/demo/data";
import { fmtTime, ROLE_LABEL } from "@/lib/format";
import { CHAT_WRITE_HINT, chatWriteState } from "@/realtime/chatPolicy";
import { realtime } from "@/services";
import { useViewState } from "@/state/viewState";
import { Button, cx, Empty, Icon } from "../ui";
import { useToast } from "../ui/Toast";

const QUICK = [
  { key: "on_my_way", label: "En camino", text: "Voy en camino al equipo." },
  { key: "arrived", label: "Llegué", text: "Llegué al equipo, inicio inspección." },
  { key: "need_part", label: "Necesito repuesto", text: "Necesito el repuesto sugerido por la IA, ¿quién lo acerca desde el almacén?" },
  { key: "safe", label: "Equipo asegurado", text: "Equipo detenido y bloqueado (LOTO). Zona segura." },
];

function useOnline() {
  const [online, setOnline] = useState(typeof navigator === "undefined" ? true : navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  return online;
}

/** Los errores de Firestore traen `code` (p. ej. permission-denied cuando las Security Rules rechazan). */
function chatError(e: unknown): string {
  const code = typeof e === "object" && e && "code" in e ? String((e as { code: unknown }).code) : "";
  if (code === "permission-denied") return "Firestore rechazó la operación (Security Rules): revisa tu rol, zona o asignación.";
  if (code === "unauthenticated") return "Sesión de Firebase vencida: vuelve a iniciar sesión.";
  return errorMessage(e);
}

function authorName(m: ChatMessage) {
  if (m.role === "sistema") return "GestionIncidente";
  const u = DEMO_USERS.find((x) => x.user_id === m.author_id);
  const t = SEED.technicians.find((x) => x.user_id === m.author_id || x.technician_id === m.author_id);
  return u?.name ?? t?.name ?? m.author_id;
}

/** Chat del incidente en Firestore (contratos.md §5): append-only, offline con caché persistente. */
export function IncidentChat({ incident }: { incident: Incident }) {
  const { me } = useAuth();
  const channel = incident.chat_channel_id ?? incident.parent_incident_id ?? incident.incident_id;
  const [messages, setMessages] = useState<ChatMessage[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  // Borrador por incidente: no se pierde al cambiar de vista
  const [draft, setDraft] = useViewState(`chat.draft.${channel}`, "");
  const [sending, setSending] = useState(false);
  const online = useOnline();
  const toast = useToast();
  const list = useRef<HTMLDivElement>(null);
  // Mismas condiciones que firestore.rules (técnico: solo si está asignado); si no, el mensaje se descartaría.
  const writeState = chatWriteState(me, incident);
  const canWrite = realtime.canChat && writeState === "ok";

  useEffect(() => {
    setMessages(null);
    return realtime.subscribeMessages(channel, setMessages, setError);
  }, [channel]);

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: "smooth" });
  }, [messages?.length]);

  const send = async (text: string, quick?: string) => {
    if (!text.trim()) return;
    setSending(true);
    try {
      await realtime.sendMessage(channel, text.trim(), quick ?? null);
      if (!quick) setDraft("");
    } catch (e) {
      toast(chatError(e), "bad");
    } finally {
      setSending(false);
    }
  };

  if (!realtime.canChat) {
    return (
      <Empty icon="forum" title="Chat no disponible">
        El chat del incidente vive en Firestore. Configura <code className="font-mono">VITE_FIREBASE_*</code> para habilitarlo (frontend/README.md).
      </Empty>
    );
  }

  return (
    <div className="flex h-full min-h-[420px] flex-col">
      {!online && (
        <div className="flex items-center gap-2 border-b border-tertiary/30 bg-tertiary/10 px-4 py-2 text-xs text-tertiary">
          <Icon name="cloud_off" className="text-[16px]" />
          Sin conexión: los mensajes se guardan en el dispositivo y se envían al reconectar.
        </div>
      )}
      <div ref={list} className="flex-1 space-y-3 overflow-y-auto p-4 scroll-thin" aria-live="polite">
        {error != null && <p className="text-xs text-error">{chatError(error)}</p>}
        {messages === null && <p className="text-xs text-on-surface-variant">Conectando al canal…</p>}
        {messages?.length === 0 && <p className="text-center text-xs text-on-surface-variant">Aún no hay mensajes.</p>}
        {messages?.map((m) => {
          const own = m.author_id === me?.user_id;
          const system = m.role === "sistema";
          if (system) {
            return (
              <div key={m.id} className="flex items-start gap-2 rounded-xl border border-hairline bg-surface-container-lowest/60 px-3 py-2 text-[11px] text-on-surface-variant">
                <Icon name="account_tree" className="mt-0.5 text-[14px] text-primary" />
                <span className="flex-1">{m.text}</span>
                <span className="shrink-0 font-mono text-[10px] text-outline">{fmtTime(m.created_at)}</span>
              </div>
            );
          }
          return (
            <div key={m.id} className={cx("flex flex-col", own ? "items-end" : "items-start")}>
              <div className="mb-0.5 flex items-center gap-1.5 font-mono text-[10px] text-outline">
                <span className="font-semibold text-on-surface-variant">{own ? "Tú" : authorName(m)}</span>
                <span>· {m.role in ROLE_LABEL ? ROLE_LABEL[m.role as keyof typeof ROLE_LABEL] : m.role}</span>
                <span>· {fmtTime(m.created_at)}</span>
                {m.pending && <Icon name="schedule" className="text-[12px] text-tertiary" />}
              </div>
              <div
                className={cx(
                  "max-w-[85%] rounded-xl px-3 py-2 text-sm",
                  own ? "rounded-br-sm bg-primary text-on-primary" : "rounded-bl-sm bg-surface-container-high text-on-surface",
                )}
              >
                {m.quick_action && (
                  <span className={cx("mb-0.5 block text-[10px] uppercase tracking-[0.06em]", own ? "text-on-primary/70" : "text-primary")}>{m.quick_action.replace(/_/g, " ")}</span>
                )}
                {m.text}
              </div>
            </div>
          );
        })}
      </div>
      {canWrite ? (
        <div className="border-t border-hairline p-3">
          <div className="mb-2 flex flex-wrap gap-1.5">
            {QUICK.map((q) => (
              <button
                key={q.key}
                type="button"
                disabled={sending}
                onClick={() => send(q.text, q.key)}
                className="rounded-full border border-hairline px-2.5 py-1 text-[11px] text-on-surface-variant hover:border-primary hover:text-primary"
              >
                {q.label}
              </button>
            ))}
          </div>
          <form
            className="flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void send(draft);
            }}
          >
            <textarea
              className="input max-h-32 min-h-[42px] flex-1 resize-none"
              rows={1}
              maxLength={2000}
              value={draft}
              placeholder="Escribe al equipo del incidente…"
              aria-label="Mensaje"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send(draft);
                }
              }}
            />
            <Button type="submit" variant="primary" icon="send" busy={sending} disabled={!draft.trim()}>
              Enviar
            </Button>
          </form>
        </div>
      ) : (
        <p className="border-t border-hairline px-4 py-3 text-center text-xs text-on-surface-variant">
          {writeState === "ok" ? CHAT_WRITE_HINT.role : CHAT_WRITE_HINT[writeState]}
        </p>
      )}
    </div>
  );
}

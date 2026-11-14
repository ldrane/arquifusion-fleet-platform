import { useEffect, useRef, useState } from "react";
import { errorMessage } from "@/api/errors";
import { Badge, Button, cx, Icon, Panel } from "@/components/ui";
import { api } from "@/services";
import { useViewState } from "@/state/viewState";

interface Turn {
  role: "user" | "assistant";
  text: string;
  tools?: string[];
  degraded?: boolean;
  error?: boolean;
}

const SUGGESTIONS = [
  "¿Qué máquinas de la zona norte están en riesgo?",
  "¿Qué repuestos están bajo el stock mínimo?",
  "¿Qué técnicos están disponibles?",
  "Estado de EX-023",
  "¿Qué preventivos están vencidos?",
  "¿Qué máquinas consumen más combustible que sus pares?",
];

/** POST /v1/assistant/chat (RF-14): tool-calling sobre datos reales, nunca SQL libre. */
export function Assistant() {
  // La conversación se conserva al navegar a otra vista y volver
  const [turns, setTurns] = useViewState<Turn[]>("assistant.turns", []);
  const [session, setSession] = useViewState<string | null>("assistant.session", null);
  const [draft, setDraft] = useViewState("assistant.draft", "");
  const [busy, setBusy] = useState(false);
  const list = useRef<HTMLDivElement>(null);

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: "smooth" });
  }, [turns.length, busy]);

  const ask = async (text: string) => {
    const msg = text.trim();
    if (!msg || busy) return;
    setTurns((t) => [...t, { role: "user", text: msg }]);
    setDraft("");
    setBusy(true);
    try {
      const r = await api.assistant(msg, session ?? undefined);
      setSession(r.session_id);
      setTurns((t) => [...t, { role: "assistant", text: r.answer, tools: r.tools_used, degraded: r.degraded }]);
    } catch (e) {
      setTurns((t) => [...t, { role: "assistant", text: errorMessage(e), error: true }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel
      icon="smart_toy"
      title="Asistente IA de flota"
      subtitle="ia-gemini · assistant_chat con herramientas sobre datos reales"
      bodyClassName="p-0"
      actions={
        turns.length > 0 && (
          <Button size="sm" variant="ghost" icon="restart_alt" onClick={() => { setTurns([]); setSession(null); }}>
            Nueva conversación
          </Button>
        )
      }
    >
      <div className="flex h-[calc(100vh-15rem)] min-h-[480px] flex-col">
        <div ref={list} className="flex-1 space-y-4 overflow-y-auto p-5 scroll-thin" aria-live="polite">
          {turns.length === 0 && (
            <div className="mx-auto flex max-w-2xl flex-col items-center gap-4 py-10 text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                <Icon name="smart_toy" className="text-[30px]" />
              </div>
              <p className="text-sm text-on-surface-variant">
                Pregunta por la flota en lenguaje natural. El asistente consulta máquinas, incidentes, técnicos, inventario y analítica con herramientas tipadas y respeta tu rol y tu zona.
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} type="button" onClick={() => void ask(s)} className="rounded-full border border-outline-variant/40 px-3 py-1.5 text-xs text-on-surface-variant hover:border-primary hover:text-primary">
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {turns.map((t, i) => (
            <div key={i} className={cx("flex", t.role === "user" ? "justify-end" : "justify-start")}>
              <div className={cx("max-w-[80%] rounded-2xl px-4 py-3 text-sm", t.role === "user" ? "rounded-br-sm bg-primary text-on-primary" : t.error ? "border border-error/30 bg-error-container/20 text-on-error-container" : "rounded-bl-sm bg-surface-container-high text-on-surface")}>
                <p className="whitespace-pre-wrap leading-relaxed">{t.text}</p>
                {t.role === "assistant" && (t.tools?.length || t.degraded) ? (
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {t.tools?.map((tool) => (
                      <span key={tool} className="chip bg-surface-container-lowest text-[10px] text-outline">
                        <Icon name="build" className="text-[12px]" />
                        {tool}
                      </span>
                    ))}
                    {t.degraded && <Badge tone="warn">Respuesta de respaldo</Badge>}
                  </div>
                ) : null}
              </div>
            </div>
          ))}
          {busy && (
            <div className="flex items-center gap-2 text-xs text-on-surface-variant">
              <span className="h-2 w-2 animate-pulse rounded-full bg-primary" />
              Consultando herramientas…
            </div>
          )}
        </div>
        <form
          className="flex items-end gap-2 border-t border-outline-variant/20 p-3"
          onSubmit={(e) => {
            e.preventDefault();
            void ask(draft);
          }}
        >
          <textarea
            className="input max-h-32 min-h-[42px] flex-1 resize-none"
            rows={1}
            maxLength={1000}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void ask(draft);
              }
            }}
            placeholder="¿Qué máquinas de la zona sur requieren mantenimiento esta semana?"
            aria-label="Pregunta al asistente"
          />
          <Button type="submit" variant="primary" icon="send" busy={busy} disabled={!draft.trim()}>
            Preguntar
          </Button>
        </form>
      </div>
    </Panel>
  );
}

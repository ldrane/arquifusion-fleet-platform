import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react";
import { errorMessage } from "@/api/errors";
import type { Incident } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { can } from "@/auth/permissions";
import { Arqui, type ArquiState, setArquiThinking } from "@/components/brand/Arqui";
import { Badge, Button, cx, Icon } from "@/components/ui";
import { ZONE_LABEL } from "@/lib/format";
import { api } from "@/services";
import { useZoned } from "@/state/FleetContext";
import { useQuery } from "@/state/queryCache";
import { useViewState } from "@/state/viewState";

interface Turn {
  role: "user" | "assistant";
  text: string;
  tools?: string[];
  degraded?: boolean;
  error?: boolean;
}

/** Preguntas rápidas (se conservan las originales). */
const SUGGESTIONS = [
  "¿Qué máquinas de la zona norte están en riesgo?",
  "¿Qué repuestos están bajo el stock mínimo?",
  "¿Qué técnicos están disponibles?",
  "Estado de EX-023",
  "¿Qué preventivos están vencidos?",
  "¿Qué máquinas consumen más combustible que sus pares?",
];

type Tone = "critical" | "warn" | "info" | "good";
interface Insight {
  id: string;
  tone: Tone;
  icon: string;
  eyebrow: string;
  title: string;
  detail: string;
  prompt: string;
}

const OPEN = (i: Incident) => i.status !== "closed" && !i.parent_incident_id;
const TONE_TEXT: Record<Tone, string> = { critical: "text-[#ff8a8d]", warn: "text-tertiary", info: "text-primary", good: "text-secondary" };

/** Insights proactivos de Arqui, derivados de los datos reales de la flota (mismo alcance de zona que el resto). */
function useInsights(): { insights: Insight[]; critical: number; open: number; atRisk: number; freeTechs: number; machines: number } {
  const { me } = useAuth();
  const { machines, incidents, technicians, zone } = useZoned();
  const inventory = useQuery(can(me?.role, "inventory") ? "inventory:low" : null, () => api.listInventory({ alert: "low_stock" }), { staleMs: 30_000 });

  return useMemo(() => {
    const open = incidents.filter(OPEN);
    const critical = open.filter((i) => i.severity === "critical" || i.severity === "high");
    const risky = machines.filter((m) => m.health_score < 70).sort((a, b) => a.health_score - b.health_score);
    const free = technicians.filter((t) => t.available);
    const low = inventory.data ?? [];
    const out: Insight[] = [];

    if (critical.length) {
      const first = critical[0];
      out.push({
        id: `crit-${critical.length}-${first.incident_id}`,
        tone: "critical",
        icon: "emergency_home",
        eyebrow: "Alerta crítica",
        title: `${critical.length} ${critical.length === 1 ? "incidente crítico abierto" : "incidentes críticos abiertos"}`,
        detail: `${first.machine_ids[0]} · ${first.ai_diagnosis?.probable_cause ?? "en triaje"}`,
        prompt: "¿Qué incidentes están abiertos?",
      });
    }
    if (risky.length) {
      const byZone = new Map<string, number>();
      risky.forEach((m) => {
        const z = m.location.zone ?? "sin zona";
        byZone.set(z, (byZone.get(z) ?? 0) + 1);
      });
      const [topZone] = [...byZone.entries()].sort((a, b) => b[1] - a[1])[0];
      out.push({
        id: `risk-${risky.length}-${risky[0].machine_id}`,
        tone: "warn",
        icon: "monitor_heart",
        eyebrow: "Salud predictiva",
        title: `${risky.length} ${risky.length === 1 ? "máquina" : "máquinas"} bajo 70 de salud`,
        detail: `Peor caso ${risky[0].machine_id} (${risky[0].health_score}/100) · foco en zona ${topZone}`,
        prompt: `¿Qué máquinas de la zona ${topZone} están en riesgo?`,
      });
      out.push({
        id: `machine-${risky[0].machine_id}-${risky[0].health_score}`,
        tone: risky[0].health_score < 40 ? "critical" : "warn",
        icon: "precision_manufacturing",
        eyebrow: "Unidad a vigilar",
        title: `${risky[0].machine_id} · ${risky[0].health_score}/100`,
        detail: `${risky[0].model} · zona ${risky[0].location.zone ?? "—"}`,
        prompt: `Estado de ${risky[0].machine_id}`,
      });
    }
    if (low.length) {
      out.push({
        id: `stock-${low.length}`,
        tone: "warn",
        icon: "inventory_2",
        eyebrow: "Repuestos",
        title: `${low.length} ${low.length === 1 ? "repuesto" : "repuestos"} bajo el mínimo`,
        detail: low
          .slice(0, 2)
          .map((i) => `${i.name} (${i.warehouse_id})`)
          .join(" · "),
        prompt: "¿Qué repuestos están bajo el stock mínimo?",
      });
    }
    if (technicians.length) {
      out.push({
        id: `techs-${free.length}`,
        tone: free.length ? "good" : "warn",
        icon: "engineering",
        eyebrow: "Despacho",
        title: free.length ? `${free.length} técnicos listos para asignar` : "Sin técnicos disponibles",
        detail: `${technicians.length - free.length} en atención · ${ZONE_LABEL(zone || me?.zone)}`,
        prompt: "¿Qué técnicos están disponibles?",
      });
    }
    out.push({
      id: "fuel",
      tone: "info",
      icon: "local_gas_station",
      eyebrow: "Eficiencia",
      title: "Consumo de combustible vs. pares",
      detail: "Compara cada unidad con su modelo y zona",
      prompt: "¿Qué máquinas consumen más combustible que sus pares?",
    });

    return { insights: out.slice(0, 5), critical: critical.length, open: open.length, atRisk: risky.length, freeTechs: free.length, machines: machines.length };
  }, [machines, incidents, technicians, inventory.data, zone, me?.zone]);
}

/** Tarjeta de insight: Arqui "piensa" (barras de escaneo) y luego proyecta el dato con un enfoque suave. */
function InsightCard({ insight, index, onAsk, disabled }: { insight: Insight; index: number; onAsk: (q: string) => void; disabled: boolean }) {
  const style = { "--think": `${550 + index * 320}ms` } as CSSProperties;
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onAsk(insight.prompt)}
      className={cx("glass glass-interactive group w-full overflow-hidden rounded-xl p-4 text-left disabled:cursor-wait disabled:opacity-60", `tone-${insight.tone}`)}
      style={style}
    >
      <div className="flex items-center justify-between gap-2">
        <span className={cx("flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.06em]", TONE_TEXT[insight.tone])}>
          <Icon name={insight.icon} className="text-[15px]" />
          {insight.eyebrow}
        </span>
        <span className="relative flex h-4 items-center">
          <span className="insight-thinking flex items-center gap-1 text-[11px] text-outline">
            <Arqui state="thinking" className="h-4 w-4" />
            Analizando
          </span>
          <span className="insight-reveal absolute right-0 flex items-center gap-1 whitespace-nowrap text-[11px] text-outline">
            <span className="h-1 w-1 rounded-full bg-secondary" />
            En vivo
          </span>
        </span>
      </div>

      <div className="relative mt-3 min-h-[52px]">
        <div className="insight-thinking absolute inset-0 flex flex-col gap-2 pt-1" aria-hidden="true">
          <span className="thinking-bar h-3 w-4/5" />
          <span className="thinking-bar h-2.5 w-3/5" />
        </div>
        <div className="insight-reveal">
          <p className="text-[15px] font-semibold leading-snug tracking-[-0.01em] text-on-surface tabular-nums">{insight.title}</p>
          <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-on-surface-variant tabular-nums">{insight.detail}</p>
        </div>
      </div>

      <div className="insight-reveal mt-3 flex items-center gap-1 text-xs font-medium text-on-surface-variant transition-colors duration-200 group-hover:text-on-surface">
        Preguntar a Arqui
        <Icon name="arrow_forward" className="text-[14px] transition-transform duration-300 spring group-hover:translate-x-0.5" />
      </div>
    </button>
  );
}

function HeroStat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="flex flex-col gap-1 px-4 first:pl-0 sm:px-5">
      <span className="text-[11px] font-medium uppercase tracking-[0.06em] text-outline">{label}</span>
      <span key={value} className={cx("metric-tick text-[22px] font-semibold leading-none tracking-[-0.03em] tabular-nums", tone ?? "text-on-surface")}>
        {value}
      </span>
    </div>
  );
}

/** POST /assistant/chat (RF-14): tool-calling sobre datos reales, nunca SQL libre. */
export function Assistant() {
  // La conversación se conserva al navegar a otra vista y volver
  const [turns, setTurns] = useViewState<Turn[]>("assistant.turns", []);
  const [session, setSession] = useViewState<string | null>("assistant.session", null);
  const [draft, setDraft] = useViewState("assistant.draft", "");
  const [busy, setBusy] = useState(false);
  const list = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const { insights, critical, open, atRisk, freeTechs, machines } = useInsights();

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: "smooth" });
  }, [turns.length, busy]);

  // Arqui "piensa" en el sidebar mientras haya una consulta; si se sale de la vista a mitad, se libera
  const thinkingHeld = useRef(false);
  const releaseThinking = () => {
    if (!thinkingHeld.current) return;
    thinkingHeld.current = false;
    setArquiThinking(false);
  };
  useEffect(() => releaseThinking, []);

  const ask = async (text: string) => {
    const msg = text.trim();
    if (!msg || busy) return;
    setTurns((t) => [...t, { role: "user", text: msg }]);
    setDraft("");
    setBusy(true);
    setArquiThinking(true);
    thinkingHeld.current = true;
    try {
      const r = await api.assistant(msg, session ?? undefined);
      setSession(r.session_id);
      setTurns((t) => [...t, { role: "assistant", text: r.answer, tools: r.tools_used, degraded: r.degraded }]);
    } catch (e) {
      setTurns((t) => [...t, { role: "assistant", text: errorMessage(e), error: true }]);
    } finally {
      setBusy(false);
      releaseThinking();
      input.current?.focus();
    }
  };

  const state: ArquiState = busy ? "thinking" : critical ? "alert" : "idle";
  const lastTools = [...turns].reverse().find((t) => t.role === "assistant" && t.tools?.length)?.tools ?? [];
  const status = busy
    ? "Analizando tu consulta con herramientas de flota…"
    : critical
      ? `${critical} ${critical === 1 ? "alerta crítica requiere" : "alertas críticas requieren"} atención`
      : `En línea · monitoreando ${machines} máquinas`;

  return (
    <div className="flex flex-col gap-5">
      {/* ---------------------------------------------------------------- cabecera: Arqui como punto focal */}
      <section className={cx("glass rounded-2xl p-5 sm:p-6", state === "alert" ? "tone-critical" : "tone-info")}>
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 -z-10 rounded-2xl opacity-50 [background-image:linear-gradient(rgba(255,255,255,0.035)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.035)_1px,transparent_1px)] [background-size:32px_32px] [mask-image:radial-gradient(ellipse_at_left,black,transparent_65%)]"
        />
        <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-4">
            <div className="relative flex h-[76px] w-[76px] shrink-0 items-center justify-center rounded-2xl border border-hairline bg-black/30">
              <Arqui state={state} className="h-14 w-14" title={`Arqui: ${status}`} />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h1 className="text-[22px] font-semibold leading-tight tracking-[-0.025em] text-on-surface">Arqui</h1>
                <span className="rounded-md border border-hairline-strong px-1.5 py-px text-[11px] font-medium text-on-surface-variant">Asistente IA</span>
              </div>
              <p className="mt-0.5 text-xs text-outline">Asistente táctico de flota · ia-gemini · assistant_chat con herramientas sobre datos reales</p>
              <p className="mt-2 flex items-center gap-2 text-[13px] text-on-surface-variant" aria-live="polite">
                <span className={cx("h-1.5 w-1.5 shrink-0 rounded-full", state === "thinking" ? "bg-primary" : state === "alert" ? "bg-danger" : "bg-secondary")} />
                <span key={status} className="metric-tick">
                  {status}
                </span>
              </p>
              {lastTools.length > 0 && !busy && (
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <span className="text-[11px] text-outline">Última consulta usó</span>
                  {lastTools.map((tool) => (
                    <span key={tool} className="rounded bg-white/[0.05] px-1.5 py-px font-mono text-[10px] text-on-surface-variant">
                      {tool}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-y-3 divide-x divide-hairline">
            <HeroStat label="Máquinas" value={machines} />
            <HeroStat label="Incidentes" value={open} />
            <HeroStat label="Críticos" value={critical} tone={critical ? "text-[#ff8a8d]" : "text-on-surface"} />
            <HeroStat label="En riesgo" value={atRisk} tone={atRisk ? "text-tertiary" : "text-on-surface"} />
            <HeroStat label="Técnicos libres" value={freeTechs} tone="text-secondary" />
          </div>
        </div>
      </section>

      <div className="grid grid-cols-1 items-start gap-5 xl:grid-cols-12">
        {/* ---------------------------------------------------------------- conversación */}
        <section className="panel flex flex-col overflow-hidden xl:col-span-8">
          <header className="panel-header">
            <div className="flex min-w-0 items-center gap-2">
              <Icon name="forum" className="text-[18px] text-outline" />
              <h2 className="text-sm font-semibold tracking-tight text-on-surface">Conversación</h2>
              {session && <span className="truncate font-mono text-[11px] text-outline">· {session}</span>}
            </div>
            {turns.length > 0 && (
              <Button
                size="sm"
                variant="ghost"
                icon="restart_alt"
                onClick={() => {
                  setTurns([]);
                  setSession(null);
                }}
              >
                Nueva conversación
              </Button>
            )}
          </header>

          <div className="flex h-[calc(100vh-24rem)] min-h-[440px] flex-col">
            <div ref={list} className="flex-1 space-y-5 overflow-y-auto px-5 py-6 scroll-thin" aria-live="polite">
              {turns.length === 0 && (
                <div className="rise mx-auto flex max-w-xl flex-col items-center gap-4 py-8 text-center">
                  <Arqui state={state === "alert" ? "alert" : "idle"} className="h-16 w-16" />
                  <div>
                    <p className="text-lg font-semibold tracking-[-0.02em] text-on-surface">Hola, soy Arqui.</p>
                    <p className="mt-1.5 text-[13px] leading-relaxed text-on-surface-variant">
                      Pregunta por la flota en lenguaje natural. Consulto máquinas, incidentes, técnicos, inventario y analítica con herramientas tipadas y respeto tu
                      rol y tu zona.
                    </p>
                  </div>
                  <div className="stagger mt-1 flex flex-wrap justify-center gap-2">
                    {SUGGESTIONS.map((s) => (
                      <button
                        key={s}
                        type="button"
                        onClick={() => void ask(s)}
                        className="rounded-lg border border-hairline-strong bg-white/[0.02] px-3 py-1.5 text-xs text-on-surface-variant transition-[background-color,border-color,color,transform] duration-200 spring hover:-translate-y-px hover:border-white/20 hover:bg-white/[0.05] hover:text-on-surface active:scale-[0.97]"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {turns.map((t, i) =>
                t.role === "user" ? (
                  <div key={i} className="msg-in-right flex justify-end">
                    <div className="max-w-[80%] rounded-2xl rounded-tr-md border border-primary/20 bg-primary/[0.12] px-4 py-2.5 text-sm text-on-surface">
                      <p className="whitespace-pre-wrap leading-relaxed">{t.text}</p>
                    </div>
                  </div>
                ) : (
                  <div key={i} className="msg-in-left flex items-start gap-3">
                    <Arqui state={t.error ? "alert" : "idle"} className="mt-0.5 h-7 w-7" />
                    <div
                      className={cx(
                        "max-w-[85%] rounded-2xl rounded-tl-md border px-4 py-3 text-sm",
                        t.error ? "border-error/25 bg-error/[0.06] text-on-error-container" : "border-hairline bg-white/[0.035] text-on-surface",
                      )}
                    >
                      <p className="whitespace-pre-wrap leading-relaxed tabular-nums">{t.text}</p>
                      {t.tools?.length || t.degraded ? (
                        <div className="mt-2.5 flex flex-wrap items-center gap-1.5 border-t border-hairline pt-2.5">
                          {t.tools?.map((tool) => (
                            <span key={tool} className="inline-flex items-center gap-1 rounded bg-white/[0.05] px-1.5 py-px font-mono text-[10px] text-outline">
                              <Icon name="build" className="text-[11px]" />
                              {tool}
                            </span>
                          ))}
                          {t.degraded && <Badge tone="warn">Respuesta de respaldo</Badge>}
                        </div>
                      ) : null}
                    </div>
                  </div>
                ),
              )}

              {busy && (
                <div className="msg-in-left flex items-start gap-3 tone-info">
                  <Arqui state="thinking" className="mt-0.5 h-7 w-7" />
                  <div className="flex w-56 flex-col gap-2 rounded-2xl rounded-tl-md border border-hairline bg-white/[0.035] px-4 py-3">
                    <span className="thinking-bar h-2.5 w-full" />
                    <span className="thinking-bar h-2.5 w-2/3" />
                    <span className="text-[11px] text-outline">Consultando herramientas…</span>
                  </div>
                </div>
              )}
            </div>

            <form
              className="border-t border-hairline p-3"
              onSubmit={(e) => {
                e.preventDefault();
                void ask(draft);
              }}
            >
              <div className="flex items-end gap-2 rounded-xl border border-hairline-strong bg-surface-container-lowest p-1.5 pl-3 transition-[border-color,box-shadow] duration-200 focus-within:border-primary/50 focus-within:ring-[3px] focus-within:ring-primary/10">
                <textarea
                  ref={input}
                  className="max-h-32 min-h-[36px] flex-1 resize-none bg-transparent py-2 text-sm text-on-surface placeholder:text-outline focus:outline-none"
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
                  placeholder="Pregúntale a Arqui: ¿qué máquinas de la zona sur requieren mantenimiento esta semana?"
                  aria-label="Pregunta al asistente"
                />
                <Button type="submit" variant="primary" icon="arrow_upward" busy={busy} disabled={!draft.trim()} aria-label="Preguntar">
                  <span className="hidden sm:inline">Preguntar</span>
                </Button>
              </div>
              <p className="mt-1.5 px-1 text-[11px] text-outline">
                <kbd className="font-sans">Enter</kbd> para enviar · <kbd className="font-sans">Shift + Enter</kbd> nueva línea
              </p>
            </form>
          </div>
        </section>

        {/* ---------------------------------------------------------------- insights proactivos */}
        <aside className="flex flex-col gap-3 xl:col-span-4" aria-label="Sugerencias proactivas de Arqui">
          <div className="flex items-center justify-between px-1">
            <span className="flex items-center gap-2 text-sm font-semibold tracking-tight text-on-surface">
              <Arqui state="thinking" className="h-5 w-5" />
              Arqui detectó
            </span>
            <span className="text-[11px] text-outline">Tiempo real</span>
          </div>
          <div className="stagger flex flex-col gap-3">
            {insights.map((ins, i) => (
              <InsightCard key={ins.id} insight={ins} index={i} onAsk={(q) => void ask(q)} disabled={busy} />
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}

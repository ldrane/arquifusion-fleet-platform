import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from "react";
import { cx, Icon } from ".";

type Tone = "good" | "bad" | "info";
interface Toast {
  id: number;
  tone: Tone;
  text: string;
}

const Ctx = createContext<(text: string, tone?: Tone) => void>(() => {});

/** Avisos efímeros de resultado de acciones (reemplazan los alert() del mock de diseño). */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: Tone = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, tone, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000);
  }, []);
  const value = useMemo(() => push, [push]);
  return (
    <Ctx.Provider value={value}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-[1000] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cx(
              "pointer-events-auto flex items-start gap-2.5 rounded-xl border bg-surface-container-high/95 p-3 text-sm shadow-[0_12px_32px_-8px_rgba(0,0,0,0.7)] backdrop-blur-md",
              t.tone === "good" ? "border-secondary/40" : t.tone === "bad" ? "border-error/40" : "border-primary/30",
            )}
          >
            <Icon
              name={t.tone === "good" ? "check_circle" : t.tone === "bad" ? "error" : "info"}
              className={cx("text-[18px]", t.tone === "good" ? "text-secondary" : t.tone === "bad" ? "text-error" : "text-primary")}
              fill
            />
            <span className="flex-1 text-on-surface">{t.text}</span>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export const useToast = () => useContext(Ctx);

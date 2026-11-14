import { type ReactNode, useEffect, useRef } from "react";
import { Icon } from ".";

/** Diálogo modal accesible (Esc para cerrar, foco inicial dentro, clic fuera cierra). */
export function Modal({ title, open, onClose, children, footer }: { title: string; open: boolean; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("input, textarea, select, button")?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[900] flex items-end justify-center bg-black/60 p-4 backdrop-blur-sm sm:items-center" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title} className="flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-outline-variant/50 bg-surface-container shadow-[0_12px_32px_-8px_rgba(0,0,0,0.7)]">
        <header className="flex items-center justify-between border-b border-outline-variant/30 px-5 py-3.5">
          <h2 className="font-mono text-sm font-bold text-on-surface">{title}</h2>
          <button type="button" onClick={onClose} className="rounded-full p-1 text-on-surface-variant hover:bg-surface-container-high" aria-label="Cerrar">
            <Icon name="close" />
          </button>
        </header>
        <div className="overflow-y-auto p-5 scroll-thin">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-outline-variant/30 px-5 py-3">{footer}</footer>}
      </div>
    </div>
  );
}

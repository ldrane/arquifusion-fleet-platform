import { type ReactNode, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cx, Icon } from ".";

const EXIT_MS = 180;

/**
 * Diálogo modal accesible (Esc para cerrar, foco inicial dentro, clic fuera cierra).
 *
 * Se monta con un portal en `document.body`: si se renderizara dentro de un ancestro con `backdrop-filter`
 * o `transform` (p. ej. el header translúcido), ese ancestro pasaría a ser el bloque contenedor del
 * `position: fixed` y el diálogo quedaría recortado. Fondo de vidrio a pantalla completa y transición
 * de entrada/salida con curva tipo Apple.
 */
export function Modal({ title, open, onClose, children, footer }: { title: string; open: boolean; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  // `mounted` mantiene el diálogo en el DOM mientras corre la animación de salida
  const [mounted, setMounted] = useState(open);
  const [closing, setClosing] = useState(false);

  useEffect(() => {
    if (open) {
      setMounted(true);
      setClosing(false);
      return;
    }
    if (!mounted) return;
    setClosing(true);
    const t = window.setTimeout(() => {
      setMounted(false);
      setClosing(false);
    }, EXIT_MS);
    return () => window.clearTimeout(t);
  }, [open, mounted]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("input, textarea, select, button")?.focus();
    // Bloquea el scroll de la página detrás del diálogo
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);

  if (!mounted) return null;

  return createPortal(
    <div
      className={cx(
        "fixed inset-0 z-[900] flex items-end justify-center overflow-y-auto p-4 sm:items-center sm:p-6",
        "bg-black/45 backdrop-blur-xl backdrop-saturate-150",
        closing ? "animate-fade-out" : "animate-fade-in",
      )}
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cx(
          "my-auto flex max-h-[min(88vh,760px)] w-full max-w-lg flex-col overflow-hidden rounded-2xl",
          "bg-surface-container/90 shadow-modal backdrop-blur-2xl",
          closing ? "animate-dialog-out" : "animate-dialog-in",
        )}
      >
        <header className="flex items-center justify-between gap-4 border-b border-hairline px-5 py-4">
          <h2 className="text-[15px] font-semibold tracking-tight text-on-surface">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="-mr-1 rounded-md p-1 text-on-surface-variant transition-colors duration-150 hover:bg-white/[0.06] hover:text-on-surface"
            aria-label="Cerrar"
          >
            <Icon name="close" className="text-[18px]" />
          </button>
        </header>
        <div className="overflow-y-auto px-5 py-5 scroll-thin">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-hairline bg-black/10 px-5 py-3.5">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}

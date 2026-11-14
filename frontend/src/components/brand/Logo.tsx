import { cx } from "../ui";

/**
 * Isotipo ArquiFusion: dos plantas cuadradas desplazadas en diagonal, dibujadas como muros en L con un vano
 * (puerta) cada una. Donde se superponen, un núcleo sólido: el espacio compartido, la fusión.
 * Simetría rotacional de 180°: se lee igual desde cualquier lado de la operación.
 */
export function Logo({ className, tile = true }: { className?: string; tile?: boolean }) {
  return (
    <svg viewBox="0 0 32 32" className={cx("shrink-0", className ?? "h-7 w-7")} aria-hidden="true" fill="none">
      {tile && <rect x="0.5" y="0.5" width="31" height="31" rx="8" fill="#16181e" stroke="rgba(255,255,255,0.1)" />}
      <rect x="13" y="13" width="6" height="6" rx="0.75" fill="#adc6ff" />
      <path
        d="M19 12.5V7H15.5M11 7H7v12h5.5M13 19.5V25h3.5M21 25h4V13h-5.5"
        stroke="#e7e9ee"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Isotipo + nombre. `compact` oculta el texto en escritorio (sidebar colapsado); en móvil siempre se ve. */
export function Wordmark({ compact, subtitle = "Centro táctico de mina" }: { compact?: boolean; subtitle?: string }) {
  return (
    <span className="flex min-w-0 items-center gap-2.5">
      <Logo />
      <span
        className={cx(
          "flex min-w-0 flex-col whitespace-nowrap transition-[opacity,transform] duration-300 ease-apple",
          compact && "lg:pointer-events-none lg:-translate-x-1 lg:opacity-0",
        )}
      >
        <span className="text-[14px] font-semibold leading-tight tracking-[-0.02em] text-on-surface">ArquiFusion</span>
        <span className="text-[11px] leading-tight text-outline">{subtitle}</span>
      </span>
    </span>
  );
}

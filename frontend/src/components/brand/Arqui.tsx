import { useId, useSyncExternalStore } from "react";
import { cx } from "../ui";

export type ArquiState = "idle" | "thinking" | "alert";

const LAMP: Record<ArquiState, string> = { idle: "#ffb95f", thinking: "#adc6ff", alert: "#e5484d" };

/**
 * Arqui, la mascota del Asistente IA: un casco de minero minimalista con lámpara frontal y visor.
 * - `idle`: parpadea y la lámpara respira.
 * - `thinking`: el visor escanea de lado a lado y emite ondas de radar (procesando una consulta).
 * - `alert`: la lámpara late en rojo (hay incidentes críticos o altos abiertos).
 * Las animaciones viven en motion.css y respetan `prefers-reduced-motion`.
 */
export function Arqui({ state = "idle", className, title }: { state?: ArquiState; className?: string; title?: string }) {
  const uid = useId().replace(/:/g, "");
  const lamp = LAMP[state];
  return (
    <svg
      viewBox="0 0 48 48"
      className={cx("arqui shrink-0 overflow-visible", className ?? "h-6 w-6")}
      data-state={state}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      fill="none"
    >
      <defs>
        <clipPath id={`visor-${uid}`}>
          <rect x="13" y="29.5" width="22" height="11" rx="5.5" />
        </clipPath>
        <radialGradient id={`halo-${uid}`}>
          <stop offset="0%" stopColor={lamp} stopOpacity="0.55" />
          <stop offset="100%" stopColor={lamp} stopOpacity="0" />
        </radialGradient>
      </defs>

      {state === "thinking" && (
        <g stroke="#adc6ff" strokeWidth="1">
          <circle className="arqui-ring" cx="24" cy="24" r="21" />
          <circle className="arqui-ring arqui-ring-2" cx="24" cy="24" r="21" />
          <circle className="arqui-ring arqui-ring-3" cx="24" cy="24" r="21" />
        </g>
      )}

      <g className="arqui-float">
        {/* Halo de la lámpara */}
        <circle className="arqui-lamp" cx="24" cy="19" r="8" fill={`url(#halo-${uid})`} />
        {/* Domo del casco + nervio central */}
        <path d="M10.5 25a13.5 13.5 0 0 1 27 0z" fill="#1c1f26" stroke="rgba(255,255,255,0.16)" strokeWidth="1" />
        <path d="M24 11.8v3.4" stroke="rgba(255,255,255,0.22)" strokeWidth="1.5" strokeLinecap="round" />
        {/* Lámpara frontal */}
        <circle cx="24" cy="19.5" r="3.4" fill="#2c3039" stroke="rgba(255,255,255,0.12)" strokeWidth="0.75" />
        <circle className="arqui-lamp" cx="24" cy="19.5" r="2.1" fill={lamp} />
        {/* Ala del casco */}
        <rect x="7.5" y="24.2" width="33" height="3.3" rx="1.65" fill="#2c3039" stroke="rgba(255,255,255,0.1)" strokeWidth="0.75" />
        {/* Visor */}
        <rect x="13" y="29.5" width="22" height="11" rx="5.5" fill="#08090c" stroke="rgba(255,255,255,0.14)" strokeWidth="1" />
        <g clipPath={`url(#visor-${uid})`}>
          {state === "thinking" ? (
            <g className="arqui-scanner">
              <rect x="20" y="33.8" width="8" height="2.4" rx="1.2" fill="#adc6ff" />
              <rect x="17" y="33.8" width="14" height="2.4" rx="1.2" fill="#adc6ff" opacity="0.18" />
            </g>
          ) : (
            <g className="arqui-eyes">
              <rect x="18" y={state === "alert" ? 34.3 : 33.5} width="3.6" height={state === "alert" ? 1.8 : 3} rx="0.9" fill="#adc6ff" />
              <rect x="26.4" y={state === "alert" ? 34.3 : 33.5} width="3.6" height={state === "alert" ? 1.8 : 3} rx="0.9" fill="#adc6ff" />
            </g>
          )}
          {/* Reflejo del visor */}
          <path d="M15.5 31.2h7" stroke="rgba(255,255,255,0.1)" strokeWidth="0.8" strokeLinecap="round" />
        </g>
      </g>
    </svg>
  );
}

// ------------------------------------------------------------------ estado compartido "Arqui está pensando"
let thinking = 0;
const listeners = new Set<() => void>();

/** Marca el inicio/fin de un procesamiento de Arqui (contador: varias consultas pueden solaparse). */
export function setArquiThinking(on: boolean) {
  thinking = Math.max(0, thinking + (on ? 1 : -1));
  listeners.forEach((l) => l());
}

export function useArquiThinking(): boolean {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => thinking > 0,
  );
}

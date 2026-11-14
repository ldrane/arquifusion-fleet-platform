import { useState } from "react";
import { config, hasFirebase, isDemo } from "@/config";
import { Icon } from "../ui";

const KEY = "af.configBanner.dismissed";
const read = () => {
  try {
    return sessionStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
};

/** Nombres (nunca valores) de las variables VITE_* que faltan y hacen que el front no use la nube. */
export function missingVars(): string[] {
  const out: string[] = [];
  if (!config.apiUrl) out.push("VITE_API_URL");
  if (!isDemo || config.apiUrl) {
    if (!config.firebase.apiKey) out.push("VITE_FIREBASE_API_KEY");
    if (!config.firebase.projectId) out.push("VITE_FIREBASE_PROJECT_ID");
  }
  return out;
}

/** Aviso de configuración: discreto y descartable en demo; ámbar si el modo real queda sin Firebase (chat/tiempo real). */
export function ConfigBanner() {
  const [hidden, setHidden] = useState(read);
  const real = !isDemo && !hasFirebase;
  if (hidden || (!isDemo && hasFirebase)) return null;
  const missing = missingVars();
  const text = isDemo
    ? config.forceDemo
      ? "Modo demo forzado (VITE_FORCE_DEMO=true): los datos y la IA son simulados, no se usa AWS ni Gemini."
      : `Modo demo: faltan ${missing.join(", ")}. Los datos y la IA son simulados; define las variables y reconstruye para usar AWS/Gemini.`
    : `Sin Firebase: faltan ${missing.join(", ")}. El tiempo real cae a polling y el chat está deshabilitado. Define las variables y reconstruye.`;
  return (
    <div
      role={real ? "alert" : "status"}
      className={
        real
          ? "flex items-start gap-2 rounded-xl border border-tertiary/40 bg-tertiary/10 px-4 py-2.5 text-xs text-tertiary"
          : "flex items-start gap-2 rounded-xl border border-hairline px-4 py-2 text-[11px] text-on-surface-variant"
      }
    >
      <Icon name={real ? "warning" : "info"} className="mt-px text-[16px]" />
      <span className="flex-1">{text}</span>
      <button
        type="button"
        aria-label="Descartar aviso"
        className="rounded p-0.5 hover:bg-white/[0.06]"
        onClick={() => {
          try {
            sessionStorage.setItem(KEY, "1");
          } catch {
            /* sin storage: solo se oculta en esta sesión de la página */
          }
          setHidden(true);
        }}
      >
        <Icon name="close" className="text-[16px]" />
      </button>
    </div>
  );
}

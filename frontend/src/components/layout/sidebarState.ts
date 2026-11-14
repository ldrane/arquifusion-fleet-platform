import { useCallback, useEffect, useState } from "react";

const KEY = "af.sidebar.collapsed";

function read(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    return false; // modo privado / storage bloqueado: expandido por defecto
  }
}

/**
 * Estado colapsado del sidebar (solo escritorio, ≥ lg). Se recuerda por navegador y se alterna con `[`
 * (como Linear) cuando el foco no está en un campo de texto.
 */
export function useSidebarCollapsed() {
  const [collapsed, setCollapsed] = useState(read);

  const toggle = useCallback(() => {
    setCollapsed((c) => {
      try {
        window.localStorage.setItem(KEY, c ? "0" : "1");
      } catch {
        /* sin persistencia: el estado igual cambia en esta sesión */
      }
      return !c;
    });
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "[" || e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName))) return;
      e.preventDefault();
      toggle();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle]);

  return { collapsed, toggle };
}

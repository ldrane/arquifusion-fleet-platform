import { useLayoutEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { errorMessage } from "@/api/errors";
import { isDemo } from "@/config";
import { api } from "@/services";
import { useFleet } from "@/state/FleetContext";
import { cx, Icon } from "../ui";
import { useToast } from "../ui/Toast";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";

/** Recuerda el scroll de cada ruta: al volver a una vista se queda donde estaba. */
function useScrollMemory() {
  const { pathname } = useLocation();
  const positions = useRef(new Map<string, number>());
  const current = useRef(pathname);
  useLayoutEffect(() => {
    const prev = current.current;
    if (prev !== pathname) positions.current.set(prev, window.scrollY);
    current.current = pathname;
    window.scrollTo(0, positions.current.get(pathname) ?? 0);
  }, [pathname]);
  useLayoutEffect(() => {
    const save = () => positions.current.set(current.current, window.scrollY);
    window.addEventListener("scroll", save, { passive: true });
    return () => window.removeEventListener("scroll", save);
  }, []);
}

function StatusBar() {
  const { machines, link } = useFleet();
  const [checking, setChecking] = useState(false);
  const [latency, setLatency] = useState<number | null>(null);
  const toast = useToast();
  const silent = machines.filter((m) => m.status === "silent").length;

  const check = async () => {
    setChecking(true);
    const t0 = performance.now();
    try {
      const me = await api.me();
      const ms = Math.round(performance.now() - t0);
      setLatency(ms);
      toast(`Enlace verificado: GET /v1/me respondió en ${ms} ms (${me.role})`, "good");
    } catch (e) {
      toast(errorMessage(e), "bad");
    } finally {
      setChecking(false);
    }
  };

  return (
    <section className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-outline-variant/20 bg-surface-container-low px-5 py-3 text-xs shadow-sm">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-on-surface-variant">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-secondary" />
          Telemetría: {machines.length - silent} de {machines.length} máquinas
        </span>
        <span className="text-outline-variant">|</span>
        <span className={silent ? "font-semibold text-tertiary" : "font-semibold text-secondary"}>
          {silent ? `${silent} sin señal (heartbeat)` : "Heartbeat OK"}
        </span>
        <span className="text-outline-variant">|</span>
        <span>
          {isDemo ? "Modo demo · seeds C1" : `API ${latency != null ? `${latency} ms` : "—"}`} · tiempo real {link.kind}
        </span>
      </div>
      <button
        type="button"
        onClick={check}
        disabled={checking}
        className="flex items-center gap-1 rounded-full border border-outline-variant/20 bg-surface-container px-3 py-1 font-mono text-xs text-on-surface-variant transition-colors hover:bg-surface-bright hover:text-on-surface disabled:opacity-50"
      >
        <Icon name="sync" className={cx("text-[14px]", checking && "animate-spin")} />
        Comprobar enlace
      </button>
    </section>
  );
}

export function AppShell() {
  const [menu, setMenu] = useState(false);
  useScrollMemory();
  return (
    <div className="min-h-screen bg-background">
      <Sidebar open={menu} onClose={() => setMenu(false)} />
      <div className="lg:pl-64">
        <Header onMenu={() => setMenu(true)} />
        <main className="min-h-screen w-full pt-16">
          <div className="flex w-full flex-col gap-6 p-4 sm:p-5 xl:p-gutter-desktop">
            <Outlet />
            <StatusBar />
          </div>
        </main>
      </div>
    </div>
  );
}

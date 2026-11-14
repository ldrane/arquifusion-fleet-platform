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
import { useSidebarCollapsed } from "./sidebarState";

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
      toast(`Enlace verificado: GET /me respondió en ${ms} ms (${me.role})`, "good");
    } catch (e) {
      toast(errorMessage(e), "bad");
    } finally {
      setChecking(false);
    }
  };

  return (
    <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-hairline px-5 py-3 text-xs">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-on-surface-variant">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-secondary" />
          Telemetría: {machines.length - silent} de {machines.length} máquinas
        </span>
        <span className="h-3 w-px bg-hairline-strong" />
        <span className={silent ? "font-medium text-tertiary" : "font-medium text-secondary"}>
          {silent ? `${silent} sin señal (heartbeat)` : "Heartbeat OK"}
        </span>
        <span className="h-3 w-px bg-hairline-strong" />
        <span className="tabular-nums">
          {isDemo ? "Modo demo · seeds C1" : `API ${latency != null ? `${latency} ms` : "—"}`} · tiempo real {link.kind}
        </span>
      </div>
      <button
        type="button"
        onClick={check}
        disabled={checking}
        className="flex h-7 items-center gap-1.5 rounded-lg border border-hairline-strong px-2.5 text-xs font-medium text-on-surface-variant transition-colors duration-150 hover:bg-white/[0.05] hover:text-on-surface disabled:opacity-50"
      >
        <Icon name="sync" className={cx("text-[14px]", checking && "animate-spin")} />
        Comprobar enlace
      </button>
    </section>
  );
}

export function AppShell() {
  const { pathname } = useLocation();
  const [menu, setMenu] = useState(false);
  const { collapsed, toggle } = useSidebarCollapsed();
  useScrollMemory();
  return (
    <div className="min-h-screen bg-background">
      <Sidebar open={menu} onClose={() => setMenu(false)} collapsed={collapsed} onToggle={toggle} />
      <div className={cx("transition-[padding] duration-300 ease-apple", collapsed ? "lg:pl-16" : "lg:pl-64")}>
        <Header onMenu={() => setMenu(true)} collapsed={collapsed} />
        <main className="min-h-screen w-full pt-16">
          <div className="flex w-full flex-col gap-6 p-4 sm:p-5 xl:p-gutter-desktop">
            {/* key = ruta: cada cambio de vista vuelve a montar el contenedor y dispara la entrada con resorte */}
            <div key={pathname} className="view-enter flex flex-col gap-6">
              <Outlet />
            </div>
            <StatusBar />
          </div>
        </main>
      </div>
    </div>
  );
}

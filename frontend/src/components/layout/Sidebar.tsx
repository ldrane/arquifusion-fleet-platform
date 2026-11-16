import { NavLink } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { navFor } from "@/auth/permissions";
import { isDemo } from "@/config";
import { openIncidents } from "@/lib/incidents";
import { useFleet } from "@/state/FleetContext";
import { Arqui, useArquiThinking } from "../brand/Arqui";
import { Wordmark } from "../brand/Logo";
import { cx, Icon } from "../ui";

const KIND_LABEL = { demo: "Simulación", firestore: "Firestore", polling: "Polling API" } as const;

/** Texto que se desvanece y desliza al colapsar; el ancho lo recorta el `overflow-hidden` del aside. */
const fade = (collapsed: boolean) =>
  cx("whitespace-nowrap transition-[opacity,transform] duration-300 ease-apple", collapsed && "lg:pointer-events-none lg:-translate-x-1 lg:opacity-0");

export function Sidebar({ open, onClose, collapsed, onToggle }: { open: boolean; onClose: () => void; collapsed: boolean; onToggle: () => void }) {
  const { role } = useAuth();
  const { link, incidents } = useFleet();
  const openList = openIncidents(incidents);
  const openCount = openList.length;
  const arquiThinking = useArquiThinking();
  const arquiState = arquiThinking ? "thinking" : openList.some((i) => i.severity === "critical" || i.severity === "high") ? "alert" : "idle";
  const ago = link.lastUpdate ? Math.max(0, Math.round((Date.now() - link.lastUpdate) / 1000)) : null;
  const statusTone = link.status === "live" ? "bg-secondary" : link.status === "error" ? "bg-error" : "bg-tertiary";
  const statusText = link.status === "live" ? `${ago ?? 0}s` : link.status === "error" ? "Error" : "Conectando";
  const channel = KIND_LABEL[link.kind as keyof typeof KIND_LABEL] ?? link.kind;

  return (
    <>
      <div
        className={cx(
          "fixed inset-0 z-40 bg-black/40 backdrop-blur-sm transition-opacity duration-300 ease-apple lg:hidden",
          open ? "opacity-100" : "pointer-events-none opacity-0",
        )}
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        className={cx(
          "fixed left-0 top-0 z-50 flex h-full w-64 flex-col overflow-hidden border-r border-hairline bg-surface-container-lowest",
          "transition-[width,transform] duration-300 ease-apple lg:translate-x-0",
          collapsed ? "lg:w-16" : "lg:w-64",
          open ? "translate-x-0" : "-translate-x-full",
        )}
        aria-label="Barra lateral"
      >
        {/* Marca */}
        <div className="flex h-16 shrink-0 items-center justify-between px-[18px]">
          <Wordmark compact={collapsed} />
          <button type="button" className="rounded-md p-1 text-on-surface-variant hover:bg-white/[0.06] lg:hidden" onClick={onClose} aria-label="Cerrar menú">
            <Icon name="close" className="text-[18px]" />
          </button>
        </div>

        {/* Navegación */}
        <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto overflow-x-hidden px-2 py-2 scroll-thin" aria-label="Navegación principal">
          {navFor(role).map((n) => {
            const badge = n.path === "/incidentes" && openCount > 0;
            return (
              <NavLink
                key={n.path}
                to={n.path}
                end={n.path === "/"}
                onClick={onClose}
                title={collapsed ? n.label : undefined}
                className={({ isActive }) =>
                  cx(
                    "group relative flex h-9 items-center gap-3 rounded-lg px-3.5 text-[13px] transition-colors duration-150",
                    isActive ? "bg-white/[0.06] font-medium text-on-surface" : "text-on-surface-variant hover:bg-white/[0.04] hover:text-on-surface",
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <span className="relative flex shrink-0">
                      {n.icon === "arqui" ? (
                        <Arqui state={arquiState} className="-m-0.5 h-6 w-6" />
                      ) : (
                        <Icon name={n.icon} className={cx("text-[20px] transition-colors", isActive ? "text-primary" : "text-outline group-hover:text-on-surface-variant")} />
                      )}
                      {badge && collapsed && <span className="absolute -right-0.5 -top-0.5 hidden h-2 w-2 rounded-full bg-error ring-2 ring-surface-container-lowest lg:block" />}
                    </span>
                    <span className={cx("flex-1", fade(collapsed))}>{n.label}</span>
                    {badge && (
                      <span className={cx("rounded-md bg-error/[0.12] px-1.5 text-[11px] font-medium tabular-nums text-error", fade(collapsed))}>{openCount}</span>
                    )}
                  </>
                )}
              </NavLink>
            );
          })}
        </nav>

        {/* Estado de sincronización + colapsar */}
        <div className="flex shrink-0 flex-col gap-1 border-t border-hairline p-2">
          <div
            className={cx("flex items-center gap-3 rounded-lg px-3.5 py-2", link.error && !collapsed && "items-start")}
            title={collapsed ? `Sincronización: ${statusText} · ${channel}` : undefined}
          >
            <span className="relative flex h-5 w-5 shrink-0 items-center justify-center">
              {link.status === "live" && <span className={cx("absolute h-2 w-2 rounded-full af-ping opacity-60", statusTone)} />}
              <span className={cx("relative h-2 w-2 rounded-full", statusTone)} />
            </span>
            <span className={cx("flex min-w-0 flex-1 flex-col text-xs", fade(collapsed))}>
              <span className="flex items-center justify-between gap-2">
                <span className="font-medium text-on-surface">{channel}</span>
                <span className="tabular-nums text-outline">{statusText}</span>
              </span>
              <span className="text-outline">OP-01{isDemo ? " · demo" : ""}</span>
              {link.error && <span className="mt-1 whitespace-normal text-[11px] leading-tight text-error">{link.error}</span>}
            </span>
          </div>
          <button
            type="button"
            onClick={onToggle}
            className="hidden h-9 items-center gap-3 rounded-lg px-3.5 text-[13px] text-outline transition-colors duration-150 hover:bg-white/[0.04] hover:text-on-surface lg:flex"
            title={collapsed ? "Expandir barra lateral  [" : "Contraer barra lateral  ["}
            aria-label={collapsed ? "Expandir barra lateral" : "Contraer barra lateral"}
            aria-expanded={!collapsed}
          >
            <Icon name={collapsed ? "left_panel_open" : "left_panel_close"} className="shrink-0 text-[20px]" />
            <span className={cx("flex flex-1 items-center justify-between", fade(collapsed))}>
              Contraer
              <kbd className="rounded border border-hairline-strong px-1.5 font-sans text-[10px] text-outline">[</kbd>
            </span>
          </button>
        </div>
      </aside>
    </>
  );
}

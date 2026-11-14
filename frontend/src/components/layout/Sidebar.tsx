import { NavLink } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { navFor } from "@/auth/permissions";
import { isDemo } from "@/config";
import { useFleet } from "@/state/FleetContext";
import { cx, Icon } from "../ui";

const KIND_LABEL = { demo: "Simulación", firestore: "Firestore", polling: "Polling API" } as const;

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { role } = useAuth();
  const { link, incidents } = useFleet();
  const openCount = incidents.filter((i) => i.status !== "closed" && !i.parent_incident_id).length;
  const ago = link.lastUpdate ? Math.max(0, Math.round((Date.now() - link.lastUpdate) / 1000)) : null;

  return (
    <>
      {open && <div className="fixed inset-0 z-40 bg-black/50 lg:hidden" onClick={onClose} aria-hidden="true" />}
      <aside
        className={cx(
          "fixed left-0 top-0 z-50 flex h-full w-64 flex-col justify-between bg-surface-container-low shadow-[0_1px_8px_rgba(0,0,0,0.4)] transition-transform lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex flex-col">
          <div className="flex h-16 items-center justify-between bg-surface-container-lowest px-4">
            <span className="font-mono text-label-md uppercase tracking-wider text-primary">Sistema Táctico de Flota</span>
            <button type="button" className="rounded-full p-1 text-on-surface-variant lg:hidden" onClick={onClose} aria-label="Cerrar menú">
              <Icon name="close" />
            </button>
          </div>
          <nav className="flex flex-col gap-1 px-2 py-3" aria-label="Navegación principal">
            {navFor(role).map((n) => (
              <NavLink
                key={n.path}
                to={n.path}
                end={n.path === "/"}
                onClick={onClose}
                className={({ isActive }) =>
                  cx(
                    "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-all",
                    isActive
                      ? "border border-primary/20 bg-primary/10 font-semibold text-primary"
                      : "border border-transparent text-on-surface-variant hover:bg-surface-container hover:text-on-surface",
                  )
                }
              >
                <Icon name={n.icon} />
                <span className="flex-1">{n.label}</span>
                {n.path === "/incidentes" && openCount > 0 && (
                  <span className="rounded-full bg-error/20 px-2 font-mono text-[10px] font-bold text-error">{openCount}</span>
                )}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="m-2 flex flex-col gap-1 rounded-xl border border-outline-variant/30 bg-surface-container-lowest p-3">
          <div className="flex items-center justify-between">
            <span className="font-mono text-label-sm uppercase text-outline">Sincronización</span>
            <span
              className={cx(
                "flex items-center gap-1.5 font-mono text-label-sm font-medium",
                link.status === "live" ? "text-secondary" : link.status === "error" ? "text-error" : "text-tertiary",
              )}
            >
              <span
                className={cx(
                  "inline-block h-2 w-2 rounded-full",
                  link.status === "live" ? "animate-pulse bg-secondary" : link.status === "error" ? "bg-error" : "bg-tertiary",
                )}
              />
              {link.status === "live" ? `${ago ?? 0}s` : link.status === "error" ? "Error" : "Conectando"}
            </span>
          </div>
          <div className="flex items-center justify-between font-mono text-label-sm text-on-surface-variant">
            <span>Canal</span>
            <span className="font-semibold text-on-surface">{KIND_LABEL[link.kind as keyof typeof KIND_LABEL] ?? link.kind}</span>
          </div>
          <div className="flex items-center justify-between font-mono text-label-sm text-on-surface-variant">
            <span>Operación</span>
            <span className="font-semibold text-on-surface">OP-01 {isDemo ? "· demo" : ""}</span>
          </div>
          {link.error && <p className="mt-1 text-[11px] leading-tight text-error">{link.error}</p>}
        </div>
      </aside>
    </>
  );
}

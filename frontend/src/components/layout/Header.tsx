import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { isDemo } from "@/config";
import { DEMO_USERS, ZONES } from "@/demo/data";
import { ROLE_LABEL, timeAgo, ZONE_LABEL } from "@/lib/format";
import { useFleet } from "@/state/FleetContext";
import { resetViewState } from "@/state/viewState";
import { Logo } from "../brand/Logo";
import { cx, Icon, sevStyle } from "../ui";
import { SimulatorControl } from "./SimulatorControl";

function useOutside(ref: React.RefObject<HTMLElement>, onOut: () => void, active: boolean) {
  useEffect(() => {
    if (!active) return;
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && onOut();
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [ref, onOut, active]);
}

/** Popover flotante: vidrio oscuro con anillo de 1px y sombra difusa. */
const POPOVER = "absolute right-0 top-11 overflow-hidden rounded-xl bg-surface-container/95 shadow-pop backdrop-blur-xl animate-dialog-in";

export function Header({ onMenu, collapsed }: { onMenu: () => void; collapsed: boolean }) {
  const { me, name, logout, loginDemo } = useAuth();
  const { zone, setZone, link, notifications, unread, markRead, machines } = useFleet();
  const [bell, setBell] = useState(false);
  const [menu, setMenu] = useState(false);
  const bellRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  useOutside(bellRef, () => setBell(false), bell);
  useOutside(menuRef, () => setMenu(false), menu);

  const visibleNotifications = notifications.filter((n) => !zone || !n.zone || n.zone === zone).slice(0, 12);
  const reporting = machines.filter((m) => m.status !== "silent").length;

  return (
    <header
      className={cx(
        "fixed left-0 right-0 top-0 z-30 h-16 border-b border-hairline bg-background/75 backdrop-blur-xl backdrop-saturate-150",
        "transition-[left] duration-300 ease-apple",
        collapsed ? "lg:left-16" : "lg:left-64",
      )}
    >
      <div className="flex h-16 w-full items-center justify-between gap-3 px-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <button type="button" className="rounded-md p-1.5 text-on-surface-variant hover:bg-white/[0.06] lg:hidden" onClick={onMenu} aria-label="Abrir menú">
            <Icon name="menu" />
          </button>
          <Link to="/" className="flex items-center gap-2.5 lg:hidden" aria-label="ArquiFusion, inicio">
            <Logo />
            <span className="hidden text-[14px] font-semibold tracking-[-0.02em] text-on-surface sm:inline">ArquiFusion</span>
          </Link>
          <label className="hidden h-8 items-center gap-2 rounded-lg border border-hairline-strong px-2.5 transition-colors duration-150 hover:bg-white/[0.04] md:flex">
            <span className="h-1.5 w-1.5 rounded-full bg-secondary" />
            <span className="sr-only">Zona</span>
            <select
              className="cursor-pointer bg-transparent pr-1 text-[13px] font-medium text-on-surface focus:outline-none disabled:cursor-default"
              value={zone}
              disabled={!!me?.zone}
              onChange={(e) => setZone(e.target.value)}
              title={me?.zone ? "Tu usuario está limitado a esta zona" : "Filtrar por zona"}
            >
              <option className="bg-surface-container-high" value="">
                OP-01 · {ZONE_LABEL(null)}
              </option>
              {ZONES.map((z) => (
                <option key={z} className="bg-surface-container-high" value={z}>
                  OP-01 · {ZONE_LABEL(z)}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="flex items-center gap-2 sm:gap-3">
          <div className="hidden items-center gap-2.5 text-xs tabular-nums text-on-surface-variant xl:flex" title="Máquinas reportando / actualizaciones de tiempo real por minuto">
            <span className={cx("h-1.5 w-1.5 rounded-full", link.status === "live" ? "bg-secondary" : "bg-tertiary")} />
            <span>
              <span className="font-medium text-on-surface">{reporting}</span>/{machines.length} reportando
            </span>
            <span className="h-3 w-px bg-hairline-strong" />
            <span>{link.updatesPerMin} upd/min</span>
          </div>

          {isDemo && <SimulatorControl />}

          <div className="relative" ref={bellRef}>
            <button
              type="button"
              className="relative rounded-lg p-1.5 text-on-surface-variant transition-colors duration-150 hover:bg-white/[0.06] hover:text-on-surface"
              onClick={() => {
                setBell((b) => !b);
                if (!bell) markRead();
              }}
              aria-label={`Notificaciones (${unread} sin leer)`}
              aria-expanded={bell}
            >
              <Icon name="notifications" />
              {unread > 0 && (
                <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-semibold tabular-nums text-white ring-2 ring-background">
                  {unread > 9 ? "9+" : unread}
                </span>
              )}
            </button>
            {bell && (
              <div className={cx(POPOVER, "w-[min(360px,calc(100vw-1.5rem))]")}>
                <div className="flex items-center justify-between border-b border-hairline px-4 py-3">
                  <span className="text-[13px] font-semibold text-on-surface">Notificaciones</span>
                  <span className="text-[11px] text-outline">push · email · dashboard</span>
                </div>
                <ul className="max-h-96 overflow-y-auto scroll-thin">
                  {visibleNotifications.length === 0 && <li className="px-4 py-6 text-center text-xs text-on-surface-variant">Sin notificaciones</li>}
                  {visibleNotifications.map((n) => (
                    <li key={n.id}>
                      <button
                        type="button"
                        className="flex w-full items-start gap-2.5 px-4 py-2.5 text-left transition-colors duration-150 hover:bg-white/[0.04]"
                        onClick={() => {
                          setBell(false);
                          if (n.incident_id) navigate(`/incidentes/${n.incident_id}`);
                          else if (n.kind === "parts.shortage") navigate("/inventario");
                        }}
                      >
                        <span className={cx("mt-1.5 h-2 w-2 shrink-0 rounded-full", sevStyle(n.severity).dot)} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-xs font-semibold text-on-surface">{n.title}</span>
                          <span className="block truncate text-[11px] text-on-surface-variant">{n.body}</span>
                        </span>
                        <span className="shrink-0 text-[11px] tabular-nums text-outline">{timeAgo(n.at)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <div className="relative" ref={menuRef}>
            <button
              type="button"
              className="flex items-center gap-2 rounded-lg py-1 pl-1 pr-1.5 transition-colors duration-150 hover:bg-white/[0.04]"
              onClick={() => setMenu((m) => !m)}
              aria-expanded={menu}
              aria-label="Menú de usuario"
            >
              <span className="relative flex h-7 w-7 items-center justify-center rounded-full bg-white/[0.08] text-[11px] font-semibold text-on-surface ring-1 ring-hairline-strong">
                {(name ?? me?.user_id ?? "?").split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase()}
                <span className="absolute -bottom-0.5 -right-0.5 h-2 w-2 rounded-full bg-secondary ring-2 ring-background" />
              </span>
              <span className="hidden flex-col text-left sm:flex">
                <span className="text-xs font-semibold text-on-surface">{name ?? me?.user_id}</span>
                <span className="text-[11px] text-outline">{me ? ROLE_LABEL[me.role] : ""}</span>
              </span>
              <Icon name="expand_more" className="hidden text-[18px] text-outline sm:inline-block" />
            </button>
            {menu && me && (
              <div className={cx(POPOVER, "w-72")}>
                <div className="border-b border-hairline px-4 py-3 text-xs">
                  <div className="text-[13px] font-semibold text-on-surface">{name}</div>
                  <div className="mt-0.5 text-outline">
                    <span className="font-mono">{me.user_id}</span> · {me.email ?? "sin email"}
                  </div>
                  <div className="mt-2 inline-flex rounded-md bg-primary/[0.1] px-1.5 py-0.5 text-[11px] font-medium text-primary">
                    {ROLE_LABEL[me.role]} · {ZONE_LABEL(me.zone)}
                  </div>
                </div>
                {isDemo && (
                  <div className="border-b border-hairline py-1">
                    <div className="px-4 pb-1 pt-2 label">Cambiar usuario demo</div>
                    {DEMO_USERS.map((u) => (
                      <button
                        key={u.user_id}
                        type="button"
                        onClick={() => {
                          setMenu(false);
                          loginDemo(u.user_id);
                          navigate("/");
                        }}
                        className={cx(
                          "flex w-full items-center justify-between px-4 py-1.5 text-left text-xs transition-colors duration-150 hover:bg-white/[0.04]",
                          u.user_id === me.user_id ? "text-on-surface" : "text-on-surface-variant",
                        )}
                      >
                        <span>{u.name}</span>
                        <span className="text-[11px] text-outline">{u.role}</span>
                      </button>
                    ))}
                  </div>
                )}
                <button
                  type="button"
                  className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-xs text-on-surface-variant transition-colors duration-150 hover:bg-white/[0.04] hover:text-on-surface"
                  onClick={() => {
                    resetViewState();
                    logout();
                  }}
                >
                  <Icon name="logout" className="text-[16px]" />
                  Cerrar sesión
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}

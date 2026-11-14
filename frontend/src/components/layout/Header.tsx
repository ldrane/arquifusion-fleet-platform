import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { isDemo } from "@/config";
import { DEMO_USERS, ZONES } from "@/demo/data";
import { ROLE_LABEL, timeAgo, ZONE_LABEL } from "@/lib/format";
import { useFleet } from "@/state/FleetContext";
import { resetViewState } from "@/state/viewState";
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

export function Logo() {
  return (
    <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden="true">
      <rect width="32" height="32" rx="6" fill="#0a0e18" stroke="#424754" />
      <path d="M6 24 L16 6 L26 24 Z" fill="none" stroke="#adc6ff" strokeWidth="2.5" strokeLinejoin="round" />
      <circle cx="16" cy="18" r="3" fill="#4edea3" />
    </svg>
  );
}

export function Header({ onMenu }: { onMenu: () => void }) {
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
    <header className="fixed left-0 right-0 top-0 z-30 h-16 bg-surface-container-low/95 shadow-[0_1px_8px_rgba(0,0,0,0.5)] backdrop-blur-md lg:left-64">
      <div className="flex h-16 w-full items-center justify-between gap-3 border-b border-outline-variant/20 px-3 sm:px-5">
        <div className="flex min-w-0 items-center gap-3">
          <button type="button" className="rounded-full p-2 text-on-surface-variant hover:bg-surface-container lg:hidden" onClick={onMenu} aria-label="Abrir menú">
            <Icon name="menu" />
          </button>
          <Link to="/" className="flex items-center gap-2.5">
            <Logo />
            <div className="hidden flex-col sm:flex">
              <span className="font-mono text-[13px] font-bold uppercase tracking-wider text-on-surface">ArquiFusion</span>
              <span className="font-mono text-[10px] uppercase tracking-wider text-outline">Centro Táctico de Mina</span>
            </div>
          </Link>
          <label className="hidden items-center gap-2 rounded-full border border-outline-variant/30 bg-surface-container px-3 py-1.5 md:flex">
            <span className="h-2 w-2 rounded-full bg-secondary shadow-[0_0_6px_#4edea3]" />
            <span className="sr-only">Zona</span>
            <select
              className="cursor-pointer bg-transparent pr-1 text-xs font-medium text-on-surface focus:outline-none disabled:cursor-default"
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
          <div className="hidden items-center gap-2 rounded-full border border-outline-variant/20 bg-surface-container-lowest px-3 py-1 font-mono text-xs xl:flex" title="Máquinas reportando / actualizaciones de tiempo real por minuto">
            <span className={cx("h-2 w-2 rounded-full", link.status === "live" ? "animate-pulse bg-secondary" : "bg-tertiary")} />
            <span className="font-medium text-secondary">{reporting}/{machines.length} reportando</span>
            <span className="text-outline">|</span>
            <span className="text-on-surface-variant">{link.updatesPerMin} upd/min</span>
          </div>

          {isDemo && <SimulatorControl />}

          <div className="relative" ref={bellRef}>
            <button
              type="button"
              className="relative rounded-full p-2 text-on-surface-variant transition-colors hover:bg-surface-container hover:text-on-surface"
              onClick={() => {
                setBell((b) => !b);
                if (!bell) markRead();
              }}
              aria-label={`Notificaciones (${unread} sin leer)`}
              aria-expanded={bell}
            >
              <Icon name="notifications" />
              {unread > 0 && (
                <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-error px-1 font-mono text-[10px] font-bold text-on-error">
                  {unread > 9 ? "9+" : unread}
                </span>
              )}
            </button>
            {bell && (
              <div className="absolute right-0 top-11 w-[min(360px,calc(100vw-1.5rem))] overflow-hidden rounded-2xl border border-outline-variant/40 bg-surface-container shadow-[0_12px_32px_-8px_rgba(0,0,0,0.7)]">
                <div className="flex items-center justify-between border-b border-outline-variant/30 px-4 py-2.5">
                  <span className="label">Notificaciones</span>
                  <span className="font-mono text-[11px] text-outline">push · email · dashboard</span>
                </div>
                <ul className="max-h-96 overflow-y-auto scroll-thin">
                  {visibleNotifications.length === 0 && <li className="px-4 py-6 text-center text-xs text-on-surface-variant">Sin notificaciones</li>}
                  {visibleNotifications.map((n) => (
                    <li key={n.id}>
                      <button
                        type="button"
                        className="flex w-full items-start gap-2.5 px-4 py-2.5 text-left hover:bg-surface-container-high"
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
                        <span className="shrink-0 font-mono text-[10px] text-outline">{timeAgo(n.at)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <div className="relative" ref={menuRef}>
            <button type="button" className="flex items-center gap-2 border-l border-outline-variant/20 pl-2" onClick={() => setMenu((m) => !m)} aria-expanded={menu} aria-label="Menú de usuario">
              <span className="relative flex h-8 w-8 items-center justify-center rounded-full bg-primary/15 font-mono text-xs font-bold text-primary ring-2 ring-primary/40">
                {(name ?? me?.user_id ?? "?").split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase()}
                <span className="absolute bottom-0 right-0 h-2 w-2 rounded-full bg-secondary ring-1 ring-surface" />
              </span>
              <span className="hidden flex-col text-left sm:flex">
                <span className="text-xs font-semibold text-on-surface">{name ?? me?.user_id}</span>
                <span className="font-mono text-[10px] text-outline">{me ? ROLE_LABEL[me.role] : ""}</span>
              </span>
              <Icon name="expand_more" className="hidden text-[18px] text-outline sm:inline-block" />
            </button>
            {menu && me && (
              <div className="absolute right-0 top-11 w-72 overflow-hidden rounded-2xl border border-outline-variant/40 bg-surface-container shadow-[0_12px_32px_-8px_rgba(0,0,0,0.7)]">
                <div className="border-b border-outline-variant/30 px-4 py-3 text-xs">
                  <div className="font-semibold text-on-surface">{name}</div>
                  <div className="font-mono text-outline">{me.user_id} · {me.email ?? "sin email"}</div>
                  <div className="mt-1 font-mono text-primary">{ROLE_LABEL[me.role]} · {ZONE_LABEL(me.zone)}</div>
                </div>
                {isDemo && (
                  <div className="border-b border-outline-variant/30 py-1">
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
                        className={cx("flex w-full items-center justify-between px-4 py-1.5 text-left text-xs hover:bg-surface-container-high", u.user_id === me.user_id ? "text-primary" : "text-on-surface-variant")}
                      >
                        <span>{u.name}</span>
                        <span className="font-mono text-[10px] text-outline">{u.role}</span>
                      </button>
                    ))}
                  </div>
                )}
                <button
                  type="button"
                  className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-xs text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface"
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

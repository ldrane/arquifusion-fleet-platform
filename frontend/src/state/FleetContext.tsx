import { createContext, type ReactNode, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { Incident, Machine, Technician } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import type { Notification } from "@/demo/world";
import { INCIDENT_STATUS_LABEL } from "@/lib/format";
import { realtime } from "@/services";
import { useViewState } from "./viewState";
import { clearQueries, invalidate } from "./queryCache";

export type LinkStatus = "connecting" | "live" | "error";

interface FleetValue {
  machines: Machine[];
  incidents: Incident[];
  technicians: Technician[];
  notifications: Notification[];
  unread: number;
  markRead(): void;
  link: { status: LinkStatus; kind: string; lastUpdate: number | null; error: string | null; updatesPerMin: number };
  /** Filtro global de zona del encabezado ("" = todas las que el usuario puede ver). */
  zone: string;
  setZone(z: string): void;
}

const Ctx = createContext<FleetValue | null>(null);

/**
 * Estado en vivo de la flota, montado UNA vez sobre todas las vistas: cambiar de pantalla no
 * reinicia la suscripción ni pierde datos. Lo alimenta el RealtimeSource del modo activo.
 */
export function FleetProvider({ children }: { children: ReactNode }) {
  const { me } = useAuth();
  const [machines, setMachines] = useState<Machine[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [technicians, setTechnicians] = useState<Technician[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [readAt, setReadAt] = useViewState<number>("fleet.notificationsReadAt", 0);
  const [zone, setZone] = useViewState<string>("fleet.zone", "");
  const [link, setLink] = useState<FleetValue["link"]>({ status: "connecting", kind: realtime.kind, lastUpdate: null, error: null, updatesPerMin: 0 });
  const prevIncidents = useRef<Map<string, Incident> | null>(null);
  const stamps = useRef<number[]>([]);

  useEffect(() => {
    if (!me) return;
    setLink((l) => ({ ...l, status: "connecting", error: null }));
    prevIncidents.current = null;
    const stop = realtime.start(
      me,
      (u) => {
        const now = Date.now();
        stamps.current = [...stamps.current.filter((t) => now - t < 60_000), now];
        if (u.machines) setMachines(u.machines);
        if (u.technicians) setTechnicians(u.technicians);
        if (u.incidents) {
          setIncidents(u.incidents);
          // Las consultas de detalle de incidentes se revalidan cuando cambia la cola
          invalidate("incident:");
          if (!realtime.subscribeNotifications) diffNotifications(u.incidents);
        }
        setLink({ status: "live", kind: realtime.kind, lastUpdate: now, error: null, updatesPerMin: stamps.current.length });
      },
      (e) => setLink((l) => ({ ...l, status: "error", error: e instanceof Error ? e.message : String(e) })),
    );
    const stopN = realtime.subscribeNotifications?.(setNotifications);
    return () => {
      stop();
      stopN?.();
      setMachines([]);
      setIncidents([]);
      setTechnicians([]);
      clearQueries();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me?.user_id, me?.role, me?.zone]);

  /** Sin feed de avisos (Firestore/polling): se derivan de los cambios de estado de la cola. */
  function diffNotifications(next: Incident[]) {
    const prev = prevIncidents.current;
    prevIncidents.current = new Map(next.map((i) => [i.incident_id, i]));
    if (!prev) return;
    const fresh: Notification[] = [];
    for (const i of next) {
      const before = prev.get(i.incident_id);
      if (before?.status === i.status && before.escalated === i.escalated) continue;
      fresh.push({
        id: `${i.incident_id}-${i.status}-${Date.now()}`,
        at: new Date().toISOString(),
        kind: !before ? "incident.detected" : i.escalated && !before.escalated ? "incident.escalated" : i.status === "closed" ? "incident.closed" : "incident.assigned",
        severity: i.severity,
        title: `${i.incident_id}: ${INCIDENT_STATUS_LABEL[i.status]}`,
        body: i.machine_ids.join(", "),
        incident_id: i.incident_id,
        zone: i.zone,
      });
    }
    if (fresh.length) setNotifications((n) => [...fresh, ...n].slice(0, 60));
  }

  // Si el usuario tiene zona, el filtro global queda fijo en ella
  const effectiveZone = me?.zone ?? zone;

  const value = useMemo<FleetValue>(
    () => ({
      machines,
      incidents,
      technicians,
      notifications,
      unread: notifications.filter((n) => new Date(n.at).getTime() > readAt && (!effectiveZone || !n.zone || n.zone === effectiveZone)).length,
      markRead: () => setReadAt(Date.now()),
      link,
      zone: effectiveZone,
      setZone,
    }),
    [machines, incidents, technicians, notifications, readAt, link, effectiveZone, setZone, setReadAt],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useFleet(): FleetValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useFleet fuera de FleetProvider");
  return v;
}

/** Colecciones ya filtradas por el selector de zona del encabezado. */
export function useZoned() {
  const f = useFleet();
  return useMemo(() => {
    const z = f.zone;
    return {
      zone: z,
      machines: z ? f.machines.filter((m) => m.location.zone === z) : f.machines,
      incidents: z ? f.incidents.filter((i) => i.zone === z) : f.incidents,
      technicians: z ? f.technicians.filter((t) => t.location.zone === z) : f.technicians,
    };
  }, [f.machines, f.incidents, f.technicians, f.zone]);
}

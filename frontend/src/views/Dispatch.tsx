import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "@/api/errors";
import type { Specialty } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { can } from "@/auth/permissions";
import { IncidentActions } from "@/components/incidents/IncidentActions";
import { IncidentCard } from "@/components/incidents/IncidentCard";
import { FleetMap } from "@/components/map/FleetMap";
import { Badge, Button, cx, Empty, Icon, IncidentStatusBadge, KpiCard, Panel, SeverityBadge } from "@/components/ui";
import { useToast } from "@/components/ui/Toast";
import { isDemo } from "@/config";
import { initials, SPECIALTY_LABEL, timeAgo } from "@/lib/format";
import { myTechnicianId } from "@/lib/ids";
import { api } from "@/services";
import { useFleet, useZoned } from "@/state/FleetContext";
import { useViewState } from "@/state/viewState";

/** Vista del técnico de campo: sus asignaciones, su disponibilidad y su ubicación (RF-16). */
function TechnicianDesk() {
  const { me } = useAuth();
  const { incidents, technicians, machines } = useFleet();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const techId = myTechnicianId(me);
  const self = technicians.find((t) => t.technician_id === techId);
  const mine = incidents.filter((i) => i.assigned_technician_id === techId && !i.parent_incident_id);
  const open = mine.filter((i) => i.status !== "closed");
  const done = mine.filter((i) => i.status === "closed").sort((a, b) => (b.resolved_at ?? "").localeCompare(a.resolved_at ?? ""));

  const update = async (body: { available?: boolean; location?: { lat: number; lon: number } }, ok: string) => {
    setBusy(true);
    try {
      await api.updateMyStatus(body);
      toast(ok, "good");
    } catch (e) {
      toast(errorMessage(e), "bad");
    } finally {
      setBusy(false);
    }
  };

  const shareLocation = () => {
    if (!navigator.geolocation) return toast("Este dispositivo no expone GPS", "bad");
    navigator.geolocation.getCurrentPosition(
      (p) => void update({ location: { lat: p.coords.latitude, lon: p.coords.longitude } }, "Ubicación enviada: alimenta el ETA del scoring"),
      () => toast("No se pudo leer la ubicación (permiso denegado)", "bad"),
      { enableHighAccuracy: true, timeout: 10_000 },
    );
  };

  return (
    <>
      <section className="panel flex flex-wrap items-center justify-between gap-4 p-5">
        <div className="flex items-center gap-4">
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/15 font-mono text-lg font-bold text-primary">{initials(self?.name ?? me?.user_id ?? "?")}</span>
          <div>
            <h1 className="font-mono text-headline-md font-bold text-on-surface">{self?.name ?? me?.user_id}</h1>
            <p className="font-mono text-xs text-outline">
              {techId} · {self?.specialties.map((s) => SPECIALTY_LABEL[s]).join(" · ")} · turno {self?.shift === "night" ? "noche" : "día"} · carga {self?.current_load ?? 0}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={self?.available ? "good" : "warn"} pulse>{self?.available ? "Disponible" : "Ocupado"}</Badge>
          <Button
            variant={self?.available ? "secondary" : "success"}
            icon={self?.available ? "do_not_disturb_on" : "check_circle"}
            busy={busy}
            onClick={() => update({ available: !self?.available }, self?.available ? "Marcado como no disponible" : "Marcado como disponible")}
          >
            {self?.available ? "Pausar asignaciones" : "Estoy disponible"}
          </Button>
          {!isDemo && <Button icon="my_location" busy={busy} onClick={shareLocation}>Enviar mi ubicación</Button>}
        </div>
      </section>

      <section className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <div className="flex flex-col gap-4">
          <h2 className="label">Mis incidentes abiertos ({open.length})</h2>
          {open.length === 0 && <div className="panel"><Empty icon="task_alt" title="No tienes incidentes asignados">Cuando GestionIncidente te asigne uno, llegará aquí y como push al móvil.</Empty></div>}
          {open.map((i) => (
            <IncidentCard key={i.incident_id} incident={i} machine={machines.find((m) => m.machine_id === i.machine_ids[0])} technician={self} />
          ))}
        </div>
        <Panel icon="history" title="Mis últimos cierres" subtitle={`${done.length} incidentes resueltos`} bodyClassName="p-0">
          <ul className="divide-y divide-outline-variant/15">
            {done.slice(0, 10).map((i) => (
              <li key={i.incident_id}>
                <Link to={`/incidentes/${i.incident_id}`} className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-surface-container">
                  <span>
                    <span className="font-mono text-xs font-semibold text-on-surface">{i.incident_id}</span>
                    <span className="ml-2 font-mono text-xs text-outline">{i.machine_ids.join(", ")}</span>
                    <span className="block text-xs text-on-surface-variant">{i.ai_diagnosis?.probable_cause}</span>
                  </span>
                  <span className="text-right font-mono text-[11px] text-outline">
                    {timeAgo(i.resolved_at)}
                    <span className="block">MTTR {i.downtime_minutes} min</span>
                  </span>
                </Link>
              </li>
            ))}
            {done.length === 0 && <li className="px-5 py-6 text-center text-xs text-on-surface-variant">Aún sin cierres.</li>}
          </ul>
        </Panel>
      </section>
    </>
  );
}

/** Vista de mantenimiento / supervisión: técnicos en vivo y cola de asignación (RF-06, RF-11). */
function DispatchBoard() {
  const { machines, incidents, technicians, zone } = useZoned();
  const [spec, setSpec] = useViewState<Specialty | "">("despacho.specialty", "");
  const [onlyFree, setOnlyFree] = useViewState("despacho.onlyFree", false);
  const open = incidents.filter((i) => i.status !== "closed" && !i.parent_incident_id);
  const pending = open.filter((i) => i.status === "detected" || i.status === "assigned");
  const working = open.filter((i) => i.status === "in_progress");
  const techs = useMemo(
    () => technicians.filter((t) => (!spec || t.specialties.includes(spec)) && (!onlyFree || t.available)).sort((a, b) => Number(b.available) - Number(a.available) || a.current_load - b.current_load),
    [technicians, spec, onlyFree],
  );
  const mtta = (() => {
    const xs = incidents.filter((i) => i.accepted_at && i.assigned_at).map((i) => (new Date(i.accepted_at!).getTime() - new Date(i.assigned_at!).getTime()) / 60000);
    return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
  })();

  return (
    <>
      <section className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <KpiCard label="Técnicos disponibles" tone="info" value={technicians.filter((t) => t.available).length} unit={`de ${technicians.length}`} description="En turno y sin carga" />
        <KpiCard label="Esperando asignación / ack" tone={pending.length ? "warn" : "good"} value={pending.length} unit="incidentes" description={`${pending.filter((i) => i.escalated).length} escalados por timeout`} />
        <KpiCard label="En atención" tone="info" value={working.length} unit="en campo" description="Con técnico en camino o en sitio" />
        <KpiCard label="Tiempo medio de aceptación" tone="neutral" value={mtta != null ? mtta.toFixed(1) : "—"} unit="min" description="De la asignación al ack" />
      </section>

      <section className="grid grid-cols-1 items-start gap-5 xl:grid-cols-12">
        <Panel className="xl:col-span-7" icon="engineering" title="Técnicos en campo" subtitle="Ubicación, carga y rutas activas" bodyClassName="p-0">
          <FleetMap machines={machines.filter((m) => m.severity !== "info")} technicians={technicians} incidents={incidents} zone={zone} className="h-[360px] w-full" />
          <div className="flex flex-wrap items-center gap-2 border-y border-outline-variant/20 bg-surface-container px-5 py-2.5">
            <select className="input w-auto py-1.5 text-xs" value={spec} onChange={(e) => setSpec(e.target.value as Specialty | "")} aria-label="Especialidad">
              <option value="">Todas las especialidades</option>
              {Object.entries(SPECIALTY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <label className="flex items-center gap-1.5 text-xs text-on-surface-variant">
              <input type="checkbox" className="accent-[#adc6ff]" checked={onlyFree} onChange={(e) => setOnlyFree(e.target.checked)} />
              Solo disponibles
            </label>
          </div>
          <ul className="grid grid-cols-1 divide-y divide-outline-variant/15 md:grid-cols-2 md:divide-y-0">
            {techs.map((t) => {
              const current = open.find((i) => i.assigned_technician_id === t.technician_id);
              return (
                <li key={t.technician_id} className="flex items-center gap-3 border-outline-variant/15 px-5 py-3 md:border-b">
                  <span className={cx("flex h-9 w-9 shrink-0 items-center justify-center rounded-xl font-mono text-xs font-bold", t.available ? "bg-primary/15 text-primary" : "bg-tertiary/15 text-tertiary")}>
                    {initials(t.name)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold text-on-surface">
                      {t.name} <span className="font-mono text-[11px] font-normal text-outline">{t.technician_id}</span>
                    </span>
                    <span className="block truncate text-[11px] text-on-surface-variant">
                      {t.specialties.map((s) => SPECIALTY_LABEL[s]).join(" · ")} · zona {t.location.zone} · {t.shift === "night" ? "noche" : "día"}
                    </span>
                    {current && (
                      <Link to={`/incidentes/${current.incident_id}`} className="block truncate font-mono text-[11px] text-primary hover:underline">
                        {current.incident_id} · {current.machine_ids[0]} ({current.status})
                      </Link>
                    )}
                  </span>
                  <span className="text-right">
                    <Badge tone={t.available ? "good" : "warn"}>{t.available ? "Libre" : "Ocupado"}</Badge>
                    <span className="mt-1 block font-mono text-[11px] text-outline">carga {t.current_load}</span>
                  </span>
                </li>
              );
            })}
            {techs.length === 0 && <li className="px-5 py-6 text-center text-xs text-on-surface-variant md:col-span-2">Ningún técnico cumple los filtros.</li>}
          </ul>
        </Panel>

        <Panel className="xl:col-span-5" icon="assignment_ind" iconTone="tertiary" title="Cola de asignación" subtitle="Detectados y esperando aceptación" bodyClassName="p-0">
          {pending.length === 0 ? (
            <Empty icon="done_all" title="Nada pendiente de asignar" />
          ) : (
            <ul className="divide-y divide-outline-variant/15">
              {pending.map((i) => (
                <li key={i.incident_id} className="flex flex-col gap-2 px-5 py-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <Link to={`/incidentes/${i.incident_id}`} className="font-mono text-sm font-bold text-on-surface hover:text-primary">
                      {i.incident_id} · {i.machine_ids.length > 1 ? `${i.machine_ids.length} máquinas` : i.machine_ids[0]}
                    </Link>
                    <span className="flex items-center gap-1.5">
                      <SeverityBadge severity={i.severity} />
                      <IncidentStatusBadge status={i.status} />
                    </span>
                  </div>
                  <p className="text-xs text-on-surface-variant">
                    {i.ai_diagnosis?.probable_cause ?? "Diagnóstico en curso"} · zona {i.zone} · {timeAgo(i.detected_at)}
                    {i.assigned_technician_id && <> · <Icon name="engineering" className="align-middle text-[14px]" /> {technicians.find((t) => t.technician_id === i.assigned_technician_id)?.name ?? i.assigned_technician_id}</>}
                    {i.escalated && <span className="ml-1 text-error">· escalado</span>}
                  </p>
                  <IncidentActions incident={i} compact />
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </section>
    </>
  );
}

export function Dispatch() {
  const { role } = useAuth();
  return can(role, "technicians") ? <DispatchBoard /> : <TechnicianDesk />;
}

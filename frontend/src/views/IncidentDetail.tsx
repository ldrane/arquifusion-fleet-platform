import { Link, useParams } from "react-router-dom";
import type { Incident } from "@/api/types";
import { IncidentActions } from "@/components/incidents/IncidentActions";
import { IncidentChat } from "@/components/incidents/IncidentChat";
import { cx, ErrorBox, HealthBar, Icon, IncidentStatusBadge, Loading, Panel, SeverityBadge, Stat, StatusDot } from "@/components/ui";
import { COMPONENT_BY_ID } from "@/demo/data";
import { fmtDateTime, fmtUsd, minutesBetween, timeAgo, VARIABLE_LABEL } from "@/lib/format";
import { api } from "@/services";
import { useFleet } from "@/state/FleetContext";
import { useQuery } from "@/state/queryCache";

/** Pasos de GestionIncidente con su hora (TRZ: cada transición emite IncidentStateChanged). */
function Lifecycle({ i }: { i: Incident }) {
  const steps = [
    { key: "detected", label: "Detectado", at: i.detected_at, icon: "notification_important" },
    { key: "assigned", label: "Asignado", at: i.assigned_at, icon: "assignment_ind" },
    { key: "in_progress", label: "Aceptado", at: i.accepted_at, icon: "build" },
    { key: "resolved", label: "Resuelto", at: i.resolved_at, icon: "task_alt" },
    { key: "closed", label: "Cerrado", at: i.status === "closed" ? (i.resolved_at ?? null) : null, icon: "inventory" },
  ];
  const order = ["detected", "assigned", "in_progress", "resolved", "closed"];
  const idx = order.indexOf(i.status);
  return (
    <ol className="grid grid-cols-5 gap-1">
      {steps.map((s, n) => {
        const done = n <= idx;
        const current = n === idx;
        return (
          <li key={s.key} className="flex flex-col items-center text-center">
            <div className="flex w-full items-center">
              <span className={cx("h-0.5 flex-1", n === 0 ? "opacity-0" : done ? "bg-primary" : "bg-outline-variant/40")} />
              <span className={cx("flex h-9 w-9 shrink-0 items-center justify-center rounded-full border-2", current ? "border-primary bg-primary text-on-primary" : done ? "border-primary bg-primary/15 text-primary" : "border-outline-variant/50 text-outline")}>
                <Icon name={s.icon} className="text-[18px]" />
              </span>
              <span className={cx("h-0.5 flex-1", n === steps.length - 1 ? "opacity-0" : n < idx ? "bg-primary" : "bg-outline-variant/40")} />
            </div>
            <span className={cx("mt-1.5 font-mono text-[11px] font-semibold", done ? "text-on-surface" : "text-outline")}>{s.label}</span>
            <span className="font-mono text-[10px] text-outline">{s.at && done ? fmtDateTime(s.at) : "—"}</span>
          </li>
        );
      })}
    </ol>
  );
}

export function IncidentDetail() {
  const { id = "" } = useParams();
  const fleet = useFleet();
  const live = fleet.incidents.find((i) => i.incident_id === id);
  const q = useQuery(`incident:${id}`, () => api.getIncident(id), { staleMs: 3000 });
  const inc = live ?? q.data;

  if (!inc && q.error) return <ErrorBox error={q.error} onRetry={q.refetch} />;
  if (!inc) return <Loading label={`Cargando ${id}…`} />;

  const parent = inc.parent_incident_id ? fleet.incidents.find((i) => i.incident_id === inc.parent_incident_id) : undefined;
  const children = fleet.incidents.filter((i) => i.parent_incident_id === inc.incident_id);
  const tech = fleet.technicians.find((t) => t.technician_id === inc.assigned_technician_id);
  const machines = inc.machine_ids.map((mid) => fleet.machines.find((m) => m.machine_id === mid)).filter(Boolean);
  const mtta = minutesBetween(inc.assigned_at, inc.accepted_at);
  const ttr = minutesBetween(inc.detected_at, inc.resolved_at);
  const d = inc.ai_diagnosis;

  return (
    <>
      <nav className="flex items-center gap-2 font-mono text-xs text-outline">
        <Link to="/incidentes" className="hover:text-primary">Historial de incidentes</Link>
        <Icon name="chevron_right" className="text-[14px]" />
        <span className="text-on-surface">{inc.incident_id}</span>
      </nav>

      <section className="panel flex flex-col gap-5 p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="font-mono text-headline-md font-bold text-on-surface">{inc.incident_id}</h1>
              <SeverityBadge severity={inc.severity} />
              <IncidentStatusBadge status={inc.status} />
              {inc.escalated && <span className="chip bg-error/20 text-error"><Icon name="trending_up" className="text-[14px]" />Escalado</span>}
              {inc.is_recurrence && <span className="chip bg-tertiary/15 text-tertiary">Recurrente</span>}
            </div>
            <p className="mt-1 font-mono text-xs text-outline">
              Zona {inc.zone} · detectado {timeAgo(inc.detected_at)} · {inc.machine_ids.length > 1 ? `incidente grupal (${inc.machine_ids.length} máquinas)` : inc.machine_ids[0]}
              {parent && <> · parte de <Link className="text-primary hover:underline" to={`/incidentes/${parent.incident_id}`}>{parent.incident_id}</Link></>}
            </p>
          </div>
          <div className="w-full sm:w-auto sm:min-w-[260px]">
            <IncidentActions incident={inc} />
            {parent && inc.status !== "closed" && <p className="text-xs text-on-surface-variant">Las acciones se toman sobre el incidente padre.</p>}
          </div>
        </div>
        <Lifecycle i={inc} />
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="Tiempo a aceptación" value={mtta != null ? `${mtta} min` : "—"} />
          <Stat label="Tiempo a resolución" value={ttr != null ? `${ttr} min` : "—"} />
          <Stat label="Fuera de servicio" value={inc.downtime_minutes != null ? `${inc.downtime_minutes} min` : "—"} />
          <Stat label="Costo" value={fmtUsd(inc.cost_usd)} />
        </div>
      </section>

      <section className="grid grid-cols-1 items-start gap-5 xl:grid-cols-12">
        <div className="flex flex-col gap-5 xl:col-span-7">
          <Panel icon="smart_toy" title="Diagnóstico IA" subtitle={d ? `${d.model_version} · ${d.prompt_version}${d.degraded ? " · fallback determinista" : ""}` : "ia-gemini · diagnose"}>
            {!d ? (
              <p className="flex items-center gap-2 text-sm text-on-surface-variant"><span className="h-2 w-2 animate-pulse rounded-full bg-primary" />Generando diagnóstico…</p>
            ) : (
              <div className="flex flex-col gap-4">
                <div>
                  <span className="label">Causa probable</span>
                  <p className="mt-1 text-sm text-on-surface">{d.probable_cause}</p>
                  {d.common_cause && <p className="mt-1 text-xs text-tertiary">Causa común del grupo: {d.common_cause}</p>}
                </div>
                <div className="rounded-xl border border-primary/20 bg-primary/5 p-3">
                  <span className="label text-primary">Acción sugerida</span>
                  <p className="mt-1 text-sm text-on-surface">{d.suggested_action}</p>
                </div>
                <div className="flex flex-wrap items-center gap-4">
                  <div className="flex items-center gap-2">
                    <span className="label">Confianza</span>
                    <div className="h-1.5 w-28 rounded-full bg-surface-container-highest"><div className="h-full rounded-full bg-primary" style={{ width: `${d.confidence * 100}%` }} /></div>
                    <span className="font-mono text-xs text-on-surface">{Math.round(d.confidence * 100)}%</span>
                  </div>
                  {d.top_factors.map((f) => (
                    <span key={f.variable} className="chip bg-surface-container-high text-on-surface-variant">
                      {VARIABLE_LABEL[f.variable]?.label ?? f.variable} {f.direction === "high" ? "▲" : "▼"} {f.z_score.toFixed(1)}σ
                    </span>
                  ))}
                </div>
              </div>
            )}
          </Panel>

          {inc.status === "closed" && (
            <Panel icon="task_alt" iconTone="secondary" title="Resumen de cierre (IA)" subtitle="summarize_chat · al cerrar">
              <p className="text-sm leading-relaxed text-on-surface">{inc.resolution_summary ?? "—"}</p>
              {inc.components_replaced.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {inc.components_replaced.map((c) => (
                    <span key={c} className="chip bg-surface-container-high text-on-surface-variant">{c} · {COMPONENT_BY_ID.get(c)?.name}</span>
                  ))}
                </div>
              )}
            </Panel>
          )}

          <Panel icon="precision_manufacturing" title="Máquinas afectadas" bodyClassName="p-0">
            <ul className="divide-y divide-outline-variant/15">
              {machines.map((m) => {
                const child = children.find((c) => c.machine_ids[0] === m!.machine_id);
                return (
                  <li key={m!.machine_id}>
                    <Link to={`/salud/${m!.machine_id}`} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 hover:bg-surface-container">
                      <span>
                        <span className="font-mono text-sm font-semibold text-on-surface">{m!.machine_id}</span>
                        <span className="ml-2 font-mono text-xs text-outline">{m!.model}</span>
                        {child && <span className="ml-2 font-mono text-[11px] text-primary">{child.incident_id}</span>}
                      </span>
                      <span className="flex items-center gap-4">
                        <StatusDot status={m!.status} />
                        <HealthBar value={m!.health_score} compact />
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </Panel>

          <Panel icon="engineering" title="Técnico asignado" subtitle={inc.technician_score != null ? `Puntaje de scoring ${inc.technician_score}` : "scoring-tecnicos"}>
            {inc.assigned_technician_id ? (
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-on-surface">{tech?.name ?? inc.assigned_technician_id}</div>
                  <div className="font-mono text-xs text-outline">{inc.assigned_technician_id} · asignado {fmtDateTime(inc.assigned_at)}{inc.accepted_at ? ` · aceptó ${fmtDateTime(inc.accepted_at)}` : " · esperando ack"}</div>
                </div>
                {tech && <span className={cx("chip", tech.available ? "bg-secondary/10 text-secondary" : "bg-tertiary/15 text-tertiary")}>{tech.available ? "Disponible" : "En atención"} · carga {tech.current_load}</span>}
              </div>
            ) : (
              <p className="text-sm text-on-surface-variant">Calculando el mejor candidato…</p>
            )}
          </Panel>
        </div>

        <Panel className="xl:col-span-5 xl:sticky xl:top-20" icon="forum" title="Canal del incidente" subtitle="Firestore · incidents/{id}/messages" bodyClassName="p-0">
          <IncidentChat incident={parent ?? inc} />
        </Panel>
      </section>
    </>
  );
}

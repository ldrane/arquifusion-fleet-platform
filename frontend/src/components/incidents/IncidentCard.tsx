import { Link } from "react-router-dom";
import type { Incident, Machine, Technician } from "@/api/types";
import { fmtTime, timeAgo, VARIABLE_LABEL } from "@/lib/format";
import { cx, Icon, IncidentStatusBadge, SeverityBadge, sevStyle, Stat } from "../ui";
import { IncidentActions } from "./IncidentActions";

/** Tarjeta de triaje (diseño "Incidentes y Triaje Prioritario"). */
export function IncidentCard({ incident, machine, technician }: { incident: Incident; machine?: Machine; technician?: Technician }) {
  const s = sevStyle(incident.severity);
  const factors = incident.ai_diagnosis?.top_factors ?? [];
  const group = incident.child_incident_ids.length > 0;
  return (
    <article className={cx("flex flex-col gap-3.5 rounded-2xl border border-l-4 border-outline-variant/30 bg-surface-container-low p-5 shadow-sm transition-all hover:border-outline-variant", s.border)}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Link to={`/incidentes/${incident.incident_id}`} className={cx("chip hover:underline", "bg-error/15", s.text)}>
              {incident.incident_id}
            </Link>
            <h3 className="font-mono text-sm font-bold text-on-surface">
              {group ? `Grupal · ${incident.machine_ids.length} máquinas` : incident.machine_ids[0]}
            </h3>
            {incident.escalated && (
              <span className="chip bg-error/20 text-error" title="Sin aceptación a tiempo: escalado al supervisor">
                <Icon name="trending_up" className="text-[14px]" />
                Escalado
              </span>
            )}
            {incident.is_recurrence && <span className="chip bg-tertiary/15 text-tertiary">Recurrente</span>}
          </div>
          <p className="mt-0.5 truncate font-mono text-xs text-outline">
            Zona {incident.zone} · {machine?.model ?? incident.machine_ids.join(", ")} · {timeAgo(incident.detected_at)}
          </p>
        </div>
        <SeverityBadge severity={incident.severity} />
      </div>

      {factors.length > 0 && (
        <div className="grid grid-cols-3 gap-2">
          {factors.slice(0, 3).map((f) => (
            <Stat
              key={f.variable}
              label={VARIABLE_LABEL[f.variable]?.label ?? f.variable}
              value={`${f.direction === "high" ? "+" : "−"}${f.z_score.toFixed(1)}σ`}
              tone={f.z_score >= 3 ? "text-error" : "text-tertiary"}
            />
          ))}
        </div>
      )}

      <div className="flex items-start gap-2.5 rounded-xl border border-outline-variant/20 bg-surface-container-lowest/80 p-3">
        <Icon name="smart_toy" className="mt-0.5 text-[18px] text-primary" />
        <div className="text-xs">
          {incident.ai_diagnosis ? (
            <>
              <span className="block font-semibold text-primary">
                Acción recomendada por IA · {Math.round(incident.ai_diagnosis.confidence * 100)}%
              </span>
              <span className="text-on-surface-variant">{incident.ai_diagnosis.suggested_action}</span>
            </>
          ) : (
            <span className="flex items-center gap-2 text-on-surface-variant">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
              Generando diagnóstico con ia-gemini…
            </span>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <IncidentStatusBadge status={incident.status} />
        <span className="font-mono text-on-surface-variant">
          {technician ? (
            <>
              <Icon name="engineering" className="mr-1 align-middle text-[14px] text-primary" />
              {technician.name}
              {incident.accepted_at ? ` · aceptó ${fmtTime(incident.accepted_at)}` : incident.assigned_at ? " · esperando ack" : ""}
            </>
          ) : incident.assigned_technician_id ? (
            incident.assigned_technician_id
          ) : (
            "Sin técnico aún"
          )}
        </span>
      </div>

      <IncidentActions incident={incident} />
    </article>
  );
}

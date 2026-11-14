import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { can } from "@/auth/permissions";
import { TelemetryChart } from "@/components/charts/Charts";
import { Badge, Empty, ErrorBox, HealthBar, Icon, Loading, Panel, Segmented, SeverityBadge, Stat, StatusDot } from "@/components/ui";
import { MODEL_BY_ID } from "@/demo/data";
import { fmt0, fmt1, fmtDate, fmtDateTime, timeAgo, TYPE_LABEL, VARIABLE_LABEL } from "@/lib/format";
import { api } from "@/services";
import { useFleet } from "@/state/FleetContext";
import { useQuery } from "@/state/queryCache";
import { useViewState } from "@/state/viewState";

const RANGES = {
  "1h": { ms: 3600_000, res: "1m" as const, label: "1 h" },
  "6h": { ms: 6 * 3600_000, res: "1m" as const, label: "6 h" },
  "24h": { ms: 24 * 3600_000, res: "1h" as const, label: "24 h" },
  "7d": { ms: 7 * 86400_000, res: "1h" as const, label: "7 d" },
};
type RangeKey = keyof typeof RANGES;

const KIND_STYLE = {
  incident: { icon: "report", tone: "text-error" },
  anomaly: { icon: "query_stats", tone: "text-tertiary" },
  preventive: { icon: "event_available", tone: "text-secondary" },
  corrective: { icon: "build", tone: "text-primary" },
};

export function MachineDetail() {
  const { id = "" } = useParams();
  const { me } = useAuth();
  const live = useFleet().machines.find((m) => m.machine_id === id);
  const [range, setRange] = useViewState<RangeKey>("machine.range", "6h");
  const detail = useQuery(`machine:${id}`, () => api.getMachine(id), { staleMs: 5000, refreshMs: 15_000 });
  // La ventana se redondea al minuto para que la clave de caché sea estable entre renders
  const to = Math.floor(Date.now() / 60_000) * 60_000;
  const from = to - RANGES[range].ms;
  const telemetry = useQuery(
    can(me?.role, "telemetry") ? `telemetry:${id}:${range}:${Math.floor(to / 300_000)}` : null,
    () => api.getTelemetry(id, new Date(from).toISOString(), new Date(to).toISOString(), RANGES[range].res),
    { staleMs: 30_000 },
  );
  const timeline = useQuery(can(me?.role, "timeline") ? `timeline:${id}` : null, () => api.getTimeline(id), { staleMs: 30_000 });
  const model = useMemo(() => MODEL_BY_ID.get(detail.data?.model ?? live?.model ?? ""), [detail.data?.model, live?.model]);

  if (detail.error) return <ErrorBox error={detail.error} onRetry={detail.refetch} />;
  if (!detail.data) return <Loading label={`Cargando ${id}…`} />;
  // Los campos que cambian en vivo (estado, health, posición) vienen del tiempo real
  const m = { ...detail.data, ...(live ?? {}) };
  const r = detail.data.latest_reading;
  const pf = detail.data.failure_probability ?? 0;

  return (
    <>
      <nav className="flex items-center gap-2 font-mono text-xs text-outline">
        <Link to="/salud" className="hover:text-primary">Salud predictiva</Link>
        <Icon name="chevron_right" className="text-[14px]" />
        <span className="text-on-surface">{m.machine_id}</span>
      </nav>

      <section className="panel flex flex-wrap items-center justify-between gap-4 p-5">
        <div className="flex items-center gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Icon name="precision_manufacturing" className="text-[26px]" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="font-mono text-headline-md font-semibold text-on-surface">{m.machine_id}</h1>
              {m.severity !== "info" && <SeverityBadge severity={m.severity} />}
              <StatusDot status={m.status} />
            </div>
            <p className="font-mono text-xs text-outline">
              {model?.brand} {m.model} · {TYPE_LABEL[m.type]} · zona {m.location.zone} · lectura {timeAgo(m.last_seen_at)}
            </p>
          </div>
        </div>
        {detail.data.open_incident_id && (
          <Link to={`/incidentes/${detail.data.open_incident_id}`} className="flex items-center gap-2 rounded-xl border border-error/40 bg-error/10 px-4 py-2 font-mono text-xs font-semibold text-error hover:bg-error/20">
            <Icon name="report" className="text-[18px]" />
            Incidente abierto {detail.data.open_incident_id}
          </Link>
        )}
      </section>

      <section className="grid grid-cols-1 gap-5 xl:grid-cols-12">
        <Panel className="xl:col-span-4" icon="monitor_heart" title="Estado predictivo" subtitle={`modelo ${detail.data.model_version ?? "—"}`}>
          <div className="flex flex-col gap-4">
            <div>
              <span className="label">Health score</span>
              <div className="mt-1 flex items-center gap-3">
                <span className="text-4xl font-semibold text-on-surface">{m.health_score}</span>
                <HealthBar value={m.health_score} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Stat label="Prob. de falla" value={`${Math.round(pf * 100)}%`} tone={pf >= 0.5 ? "text-error" : pf >= 0.25 ? "text-tertiary" : "text-secondary"} />
              <Stat label="Vida útil restante" value={`${fmt0(detail.data.rul_hours)} h`} />
              <Stat label="Horas de uso" value={fmt0(detail.data.operating_hours)} />
              <Stat label="Intervalo PM" value={`${model?.maintenance_interval_h ?? "—"} h`} />
              <Stat label="Último mant." value={fmtDate(detail.data.last_maintenance_at)} />
              <Stat
                label="Próximo mant."
                value={fmtDate(detail.data.next_maintenance_at)}
                tone={detail.data.next_maintenance_at && detail.data.next_maintenance_at < new Date().toISOString().slice(0, 10) ? "text-error" : undefined}
              />
            </div>
            <div>
              <span className="label">Variables que explican la alerta</span>
              {detail.data.top_factors.length === 0 ? (
                <p className="mt-1 text-xs text-on-surface-variant">Todas las variables dentro del rango de su cohorte.</p>
              ) : (
                <ul className="mt-2 flex flex-col gap-2">
                  {detail.data.top_factors.map((f) => (
                    <li key={f.variable} className="flex items-center gap-3">
                      <span className="w-28 text-xs text-on-surface">{VARIABLE_LABEL[f.variable]?.label ?? f.variable}</span>
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-container-highest">
                        <div className={f.z_score >= 3 ? "h-full bg-error" : "h-full bg-tertiary"} style={{ width: `${Math.min(100, (f.z_score / 5) * 100)}%` }} />
                      </div>
                      <span className="w-16 text-right font-mono text-xs text-on-surface-variant">
                        {f.direction === "high" ? "▲" : "▼"} {f.z_score.toFixed(1)}σ
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </Panel>

        <Panel
          className="xl:col-span-8"
          icon="show_chart"
          title="Telemetría"
          subtitle={r ? `Última lectura ${fmtDateTime(r.timestamp)} · estado ${r.state}` : "—"}
          actions={<Segmented label="Rango" value={range} onChange={setRange} options={Object.entries(RANGES).map(([k, v]) => ({ value: k as RangeKey, label: v.label }))} />}
        >
          {r && (
            <div className="mb-4 grid grid-cols-3 gap-2 sm:grid-cols-7">
              {(["temperature_c", "vibration_mm_s", "pressure_bar", "fuel_rate_lph", "load_pct", "speed_kmh", "rpm"] as const).map((v) => (
                <Stat key={v} label={VARIABLE_LABEL[v]!.label} value={`${fmt1(r[v])}`} />
              ))}
            </div>
          )}
          {!can(me?.role, "telemetry") ? (
            <Empty icon="lock" title="Tu rol no consulta series históricas">El operador ve el estado en vivo; la telemetría detallada es para técnicos, mantenimiento y supervisión.</Empty>
          ) : telemetry.error ? (
            <ErrorBox error={telemetry.error} onRetry={telemetry.refetch} />
          ) : !telemetry.data ? (
            <Loading label="Cargando serie…" />
          ) : telemetry.data.length === 0 ? (
            <Empty icon="sensors_off" title="Sin lecturas en este rango" />
          ) : (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {(["temperature_c", "vibration_mm_s", "pressure_bar", "fuel_rate_lph"] as const).map((v) => (
                <TelemetryChart key={v} data={telemetry.data!} variable={v} nominal={model?.nominal[v]?.[0]} resolution={RANGES[range].res} />
              ))}
              <div className="md:col-span-2">
                <TelemetryChart data={telemetry.data} variable="health_score" resolution={RANGES[range].res} />
              </div>
            </div>
          )}
        </Panel>
      </section>

      {can(me?.role, "timeline") && (
        <Panel icon="timeline" title="Línea de tiempo y confiabilidad" subtitle="GET /machines/{id}/timeline · últimos 90 días">
          {timeline.error ? (
            <ErrorBox error={timeline.error} onRetry={timeline.refetch} />
          ) : !timeline.data ? (
            <Loading />
          ) : (
            <div className="grid grid-cols-1 gap-5 lg:grid-cols-4">
              <div className="grid grid-cols-3 gap-2 lg:col-span-1 lg:grid-cols-1">
                <Stat label="MTBF" value={`${fmt1(timeline.data.kpis.mtbf_hours)} h`} />
                <Stat label="MTTR" value={`${fmt1(timeline.data.kpis.mttr_hours)} h`} />
                <Stat label="Disponibilidad" value={`${fmt1(timeline.data.kpis.availability_pct)}%`} tone="text-secondary" />
              </div>
              <ol className="relative max-h-80 overflow-y-auto border-l border-hairline pl-5 scroll-thin lg:col-span-3">
                {timeline.data.events.length === 0 && <li className="text-xs text-on-surface-variant">Sin eventos registrados.</li>}
                {timeline.data.events.map((e, i) => {
                  const s = KIND_STYLE[e.kind];
                  return (
                    <li key={`${e.ref_id}-${e.kind}-${i}`} className="mb-3">
                      <span className="absolute -left-[9px] flex h-[18px] w-[18px] items-center justify-center rounded-full bg-surface-container-low">
                        <Icon name={s.icon} className={`text-[14px] ${s.tone}`} />
                      </span>
                      <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-outline">
                        {fmtDateTime(e.at)}
                        {e.ref_id.startsWith("INC-") ? (
                          <Link to={`/incidentes/${e.ref_id}`} className="text-primary hover:underline">{e.ref_id}</Link>
                        ) : (
                          <Badge tone="neutral">{e.kind}</Badge>
                        )}
                      </div>
                      <p className="text-xs text-on-surface">{e.summary}</p>
                    </li>
                  );
                })}
              </ol>
            </div>
          )}
        </Panel>
      )}
    </>
  );
}

import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { errorMessage } from "@/api/errors";
import type { MachineStatus, MachineType } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { can } from "@/auth/permissions";
import { Badge, Button, cx, Empty, ErrorBox, HealthBar, Icon, KpiCard, Panel, SeverityBadge, StatusDot } from "@/components/ui";
import { useToast } from "@/components/ui/Toast";
import { fmtDateTime, STATUS_LABEL, timeAgo, TYPE_ICON, TYPE_LABEL } from "@/lib/format";
import { api } from "@/services";
import { useZoned } from "@/state/FleetContext";
import { invalidate, useQuery } from "@/state/queryCache";
import { useViewState } from "@/state/viewState";

type SortKey = "health" | "id" | "last_seen";

function MlModelCard() {
  const { me } = useAuth();
  const q = useQuery("ml:model", () => api.mlModel(), { staleMs: 10_000, refreshMs: 15_000 });
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const retrain = async () => {
    setBusy(true);
    try {
      const r = await api.retrain();
      toast(`Reentrenamiento iniciado: ${r.execution_arn.split(":").pop()}`, "good");
      setTimeout(() => invalidate("ml:"), 10_000);
    } catch (e) {
      toast(errorMessage(e), "bad");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel
      icon="model_training"
      title="Modelo de detección (IsolationForest)"
      subtitle="GET /ml/model · SFN Reentrenamiento"
      actions={can(me?.role, "retrain") && <Button icon="replay" busy={busy} onClick={retrain}>Reentrenar</Button>}
    >
      {q.error ? (
        <ErrorBox error={q.error} onRetry={q.refetch} />
      ) : !q.data ? (
        <p className="text-xs text-on-surface-variant">Cargando…</p>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div><span className="label">Versión</span><div className="font-mono text-xl font-semibold text-on-surface">{q.data.model_version}</div><Badge tone={q.data.promoted ? "good" : "warn"}>{q.data.promoted ? "Promovido" : "Candidato"}</Badge></div>
          <div><span className="label">Precisión</span><div className="font-mono text-xl font-semibold text-on-surface">{Math.round(q.data.precision * 100)}%</div></div>
          <div><span className="label">Recall</span><div className="font-mono text-xl font-semibold text-on-surface">{Math.round(q.data.recall * 100)}%</div></div>
          <div><span className="label">Anticipación media</span><div className="text-xl font-semibold text-secondary">{q.data.mean_lead_time_hours} h</div><span className="text-[11px] text-outline">entrenado {fmtDateTime(q.data.trained_at)}</span></div>
        </div>
      )}
    </Panel>
  );
}

function PrecursorsCard() {
  const q = useQuery("analytics:precursors", () => api.precursors(), { staleMs: 60_000 });
  return (
    <Panel
      icon="timeline"
      title="Firmas pre-falla"
      subtitle="GET /analytics/precursors · patrones que preceden a las fallas, por modelo (AnalisisDiario)"
    >
      {q.error ? (
        <ErrorBox error={q.error} onRetry={q.refetch} />
      ) : !q.data ? (
        <p className="text-xs text-on-surface-variant">Cargando...</p>
      ) : q.data.precursors.length === 0 ? (
        <Empty icon="insights" title="Aún no hay suficientes incidentes">
          La rama Precursores necesita al menos 3 incidentes cerrados por modelo.
        </Empty>
      ) : (
        <div className="grid gap-4 md:grid-cols-3">
          {q.data.precursors.map((g) => (
            <div key={g.model} className="rounded-xl border border-hairline bg-surface-container p-4">
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-mono text-sm font-semibold text-on-surface">{g.model}</span>
                <span className="text-[11px] text-outline">{g.n_incidents} fallas</span>
              </div>
              <p className="mt-1 text-sm text-on-surface">{g.headline}</p>
              <div className="mt-3 space-y-2.5">
                {g.signatures.map((s) => (
                  <div key={s.variable}>
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-mono text-on-surface-variant">{s.variable}</span>
                      <span className="text-outline">{Math.round(s.share * 100)}%</span>
                    </div>
                    <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
                      <div className="h-full rounded-full bg-primary" style={{ width: `${Math.round(s.share * 100)}%` }} />
                    </div>
                    <div className="mt-1 flex items-center gap-2 text-[11px] text-outline">
                      <span className="inline-flex items-center gap-1 rounded-full bg-white/[0.06] px-2 py-0.5 text-secondary">
                        <Icon name="schedule" className="text-[13px]" /> {s.median_lead_time_h} h de anticipación
                      </span>
                      <span>z {s.median_z >= 0 ? "+" : ""}{s.median_z.toFixed(1)}σ</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

export function PredictiveHealth() {
  const { me } = useAuth();
  const { machines, incidents } = useZoned();
  const navigate = useNavigate();
  const [query, setQuery] = useViewState("salud.query", "");
  const [type, setType] = useViewState<MachineType | "">("salud.type", "");
  const [status, setStatus] = useViewState<MachineStatus | "">("salud.status", "");
  const [risk, setRisk] = useViewState("salud.risk", false);
  const [sort, setSort] = useViewState<SortKey>("salud.sort", "health");

  const rows = useMemo(() => {
    const q = query.trim().toUpperCase();
    return machines
      .filter((m) => (!q || m.machine_id.includes(q) || m.model.toUpperCase().includes(q)) && (!type || m.type === type) && (!status || m.status === status) && (!risk || m.health_score < 70 || m.severity !== "info"))
      .sort((a, b) => (sort === "health" ? a.health_score - b.health_score : sort === "id" ? a.machine_id.localeCompare(b.machine_id) : (a.last_seen_at ?? "").localeCompare(b.last_seen_at ?? "")));
  }, [machines, query, type, status, risk, sort]);

  const avg = machines.length ? Math.round(machines.reduce((a, m) => a + m.health_score, 0) / machines.length) : 0;
  const atRisk = machines.filter((m) => m.health_score < 70).length;
  const intervention = machines.filter((m) => m.status === "needs_intervention" || m.status === "stopped").length;
  const silent = machines.filter((m) => m.status === "silent").length;

  return (
    <>
      <section className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <KpiCard label="Health medio" tone={avg >= 75 ? "good" : "warn"} value={avg} unit="/ 100" description={`${machines.length} máquinas monitoreadas`} />
        <KpiCard label="En riesgo" tone={atRisk ? "warn" : "good"} value={atRisk} unit="health < 70" description="Candidatas a adelantar preventivo" />
        <KpiCard label="Requieren intervención" tone={intervention ? "bad" : "good"} value={intervention} unit="equipos" description="Detenidas o con incidente alto/crítico" />
        <KpiCard label="Sin señal" tone={silent ? "warn" : "good"} value={silent} unit="heartbeat" description="Sin lectura en más de 3 intervalos" />
      </section>

      {(can(me?.role, "mlModel")) && <MlModelCard />}

      {can(me?.role, "precursors") && <PrecursorsCard />}

      <Panel
        icon="vital_signs"
        title="Salud de la flota"
        subtitle="Health score de procesar (reglas + z-score EWMA + IsolationForest)"
        bodyClassName="p-0"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <input className="input w-36 py-1.5 font-mono text-xs" placeholder="Buscar EX-023" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Buscar máquina" />
            <select className="input w-auto py-1.5 text-xs" value={type} onChange={(e) => setType(e.target.value as MachineType | "")} aria-label="Tipo">
              <option value="">Todos los tipos</option>
              {Object.entries(TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <select className="input w-auto py-1.5 text-xs" value={status} onChange={(e) => setStatus(e.target.value as MachineStatus | "")} aria-label="Estado">
              <option value="">Todos los estados</option>
              {Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <label className="flex items-center gap-1.5 text-xs text-on-surface-variant">
              <input type="checkbox" checked={risk} onChange={(e) => setRisk(e.target.checked)} className="accent-[#adc6ff]" />
              Solo en riesgo
            </label>
          </div>
        }
      >
        {rows.length === 0 ? (
          <Empty icon="search_off" title="Sin máquinas para estos filtros" />
        ) : (
          <div className="max-h-[640px] overflow-auto scroll-thin">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="table-head">
                <tr>
                  {([["id", "Máquina"], [null, "Tipo / modelo"], [null, "Zona"], [null, "Estado"], ["health", "Health"], [null, "Severidad"], ["last_seen", "Última lectura"], [null, "Incidente"]] as const).map(([k, label]) => (
                    <th key={label} className="px-4 py-2.5">
                      {k ? (
                        <button type="button" onClick={() => setSort(k)} className={cx("inline-flex items-center gap-1 uppercase", sort === k && "text-primary")}>
                          {label}
                          {sort === k && <Icon name="arrow_downward" className="text-[12px]" />}
                        </button>
                      ) : (
                        label
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {rows.map((m) => {
                  const inc = m.open_incident_id ? incidents.find((i) => i.incident_id === m.open_incident_id) : undefined;
                  return (
                    <tr key={m.machine_id} onClick={() => navigate(`/salud/${m.machine_id}`)} className="cursor-pointer hover:bg-surface-container" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && navigate(`/salud/${m.machine_id}`)}>
                      <td className="px-4 py-2.5 font-mono font-semibold text-on-surface">{m.machine_id}</td>
                      <td className="px-4 py-2.5 text-xs text-on-surface-variant">
                        <Icon name={TYPE_ICON[m.type]} className="mr-1.5 align-middle text-[16px] text-outline" />
                        {TYPE_LABEL[m.type]} · <span className="font-mono">{m.model}</span>
                      </td>
                      <td className="px-4 py-2.5 text-xs capitalize text-on-surface-variant">{m.location.zone}</td>
                      <td className="px-4 py-2.5"><StatusDot status={m.status} /></td>
                      <td className="px-4 py-2.5"><HealthBar value={m.health_score} /></td>
                      <td className="px-4 py-2.5">{m.severity !== "info" ? <SeverityBadge severity={m.severity} /> : <span className="text-xs text-outline">—</span>}</td>
                      <td className="px-4 py-2.5 font-mono text-xs text-on-surface-variant">{timeAgo(m.last_seen_at)}</td>
                      <td className="px-4 py-2.5 text-xs">{inc ? <span className="text-error">{inc.incident_id}</span> : <span className="text-outline">—</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="border-t border-hairline px-5 py-2 text-[11px] text-outline">{rows.length} de {machines.length} máquinas · clic en una fila para ver telemetría, factores y línea de tiempo</div>
      </Panel>
    </>
  );
}

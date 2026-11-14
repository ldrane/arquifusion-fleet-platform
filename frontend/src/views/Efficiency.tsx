import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { can } from "@/auth/permissions";
import { CLASS_LABEL, FuelDeviationChart, ProductivityMatrix } from "@/components/charts/Charts";
import { Arqui } from "@/components/brand/Arqui";
import { Badge, Empty, ErrorBox, Icon, KpiCard, Loading, Panel, Segmented } from "@/components/ui";
import { fmt1, fmtDateTime, fmtSigned, ZONE_LABEL } from "@/lib/format";
import { api } from "@/services";
import { useFleet } from "@/state/FleetContext";
import { useQuery } from "@/state/queryCache";
import { useViewState } from "@/state/viewState";

export function Efficiency() {
  const { role } = useAuth();
  const { zone } = useFleet();
  const [period, setPeriod] = useViewState<"7d" | "30d">("ef.period", "7d");
  const [view, setView] = useViewState<"chart" | "table">("ef.fuelView", "chart");
  const [prodView, setProdView] = useViewState<"chart" | "table">("ef.prodView", "chart");
  const q = { ...(zone ? { zone } : {}), period };
  const kpis = useQuery(`kpis:${zone}:${period}`, () => api.kpis(q), { staleMs: 20_000, refreshMs: 30_000 });
  const fuel = useQuery(`fuel:${zone}:${period}`, () => api.fuel(q), { staleMs: 60_000 });
  const prod = useQuery(`prod:${zone}:${period}`, () => api.productivity(q), { staleMs: 60_000 });
  const report = useQuery(can(role, "report") ? "report:daily" : null, () => api.latestReport("daily"), { staleMs: 120_000 });

  const fuelTop = useMemo(() => {
    const xs = fuel.data ?? [];
    // Los 8 con mayor desvío y los 4 más eficientes: el gráfico divergente muestra ambos extremos
    return [...xs.slice(0, 8), ...xs.slice(-4)];
  }, [fuel.data]);
  const k = kpis.data;
  const suggestions = (prod.data ?? []).filter((p) => p.redistribution_suggestion && p.classification === "overused");

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-headline-md font-semibold text-on-surface">Eficiencia operativa</h1>
          <p className="font-mono text-xs text-outline">{ZONE_LABEL(zone)} · AnalisisDiario (A7) · KPIs, combustible y productividad</p>
        </div>
        <Segmented label="Periodo" value={period} onChange={setPeriod} options={[{ value: "7d", label: "Últimos 7 días" }, { value: "30d", label: "Últimos 30 días" }]} />
      </div>

      {kpis.error ? (
        <ErrorBox error={kpis.error} onRetry={kpis.refetch} />
      ) : (
        <section className="grid grid-cols-2 gap-4 xl:grid-cols-4">
          <KpiCard label="Disponibilidad" tone={k && k.availability_pct >= 92 ? "good" : "warn"} value={k ? `${fmt1(k.availability_pct)}%` : "…"} description="Meta de operación: 92%" footer={<><span>{k?.open_incidents ?? "—"} incidentes abiertos</span><span>{k?.machines_at_risk ?? "—"} en riesgo</span></>} />
          <KpiCard label="MTBF / MTTR" tone="info" value={k ? fmt1(k.mtbf_hours) : "…"} unit="h MTBF" description={`MTTR ${k ? fmt1(k.mttr_hours) : "—"} h por incidente`} />
          <KpiCard label="Utilización de flota" tone="neutral" value={k ? `${fmt1(k.fleet_utilization_pct)}%` : "…"} description="Horas productivas / horas disponibles" />
          <KpiCard label="Costo de combustible" tone="warn" value={k ? `$${k.fuel_cost_per_ton_usd.toFixed(2)}` : "…"} unit="USD / t" description="Normalizado por tonelaje movido" />
        </section>
      )}

      {can(role, "report") && (
        <Panel icon="summarize" title="Resumen gerencial IA" subtitle={report.data ? `Generado ${fmtDateTime(report.data.generated_at)} · ${report.data.prompt_version}` : "GET /reports/latest"}>
          {report.error ? <ErrorBox error={report.error} onRetry={report.refetch} /> : !report.data ? <Loading /> : (
            <div className="flex gap-3">
              <Arqui className="h-8 w-8" />
              <p className="text-sm leading-relaxed text-on-surface">{report.data.summary_text}</p>
            </div>
          )}
        </Panel>
      )}

      <section className="grid grid-cols-1 items-start gap-5 xl:grid-cols-2">
        <Panel
          icon="local_gas_station"
          iconTone="tertiary"
          title="Consumo vs. pares del mismo modelo"
          subtitle="Naranja: consume más que sus pares · azul: menos"
          actions={<Segmented label="Vista" value={view} onChange={setView} options={[{ value: "chart", label: "Gráfico" }, { value: "table", label: "Tabla" }]} />}
        >
          {fuel.error ? <ErrorBox error={fuel.error} onRetry={fuel.refetch} /> : !fuel.data ? <Loading /> : fuel.data.length === 0 ? <Empty title="Sin datos de combustible" /> : view === "chart" ? (
            <FuelDeviationChart data={fuelTop} />
          ) : (
            <div className="max-h-[420px] overflow-auto scroll-thin">
              <table className="w-full text-left text-xs">
                <thead className="table-head"><tr><th className="px-3 py-2">Máquina</th><th className="px-3 py-2 text-right">L/h</th><th className="px-3 py-2 text-right">L/t</th><th className="px-3 py-2 text-right">vs pares</th><th className="px-3 py-2 text-right">vs historial</th><th className="px-3 py-2">Causas probables</th></tr></thead>
                <tbody className="divide-y divide-hairline">
                  {fuel.data.map((f) => (
                    <tr key={f.machine_id}>
                      <td className="px-3 py-2 font-mono font-semibold"><Link to={`/salud/${f.machine_id}`} className="hover:text-primary">{f.machine_id}</Link>{f.progressive_increase && <Icon name="trending_up" className="ml-1 align-middle text-[14px] text-tertiary" />}</td>
                      <td className="px-3 py-2 text-right font-mono">{fmt1(f.lph)}</td>
                      <td className="px-3 py-2 text-right font-mono">{f.l_per_ton.toFixed(3)}</td>
                      <td className="px-3 py-2 text-right font-mono">{fmtSigned(f.vs_peers_pct)}</td>
                      <td className="px-3 py-2 text-right font-mono">{fmtSigned(f.vs_own_history_pct)}</td>
                      <td className="px-3 py-2 text-on-surface-variant">{f.probable_causes.join(", ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {fuel.data && (
            <p className="mt-3 text-xs text-on-surface-variant">
              {fuel.data.filter((f) => f.progressive_increase).length} máquinas con aumento progresivo de consumo (posible falla en desarrollo, RF-07).
            </p>
          )}
        </Panel>

        <Panel
          icon="scatter_plot"
          title="Matriz productividad × costo"
          subtitle="Utilización vs costo por hora (RF-08)"
          actions={<Segmented label="Vista" value={prodView} onChange={setProdView} options={[{ value: "chart", label: "Gráfico" }, { value: "table", label: "Tabla" }]} />}
        >
          {prod.error ? <ErrorBox error={prod.error} onRetry={prod.refetch} /> : !prod.data ? <Loading /> : prodView === "chart" ? (
            <ProductivityMatrix data={prod.data} />
          ) : (
            <div className="max-h-[420px] overflow-auto scroll-thin">
              <table className="w-full text-left text-xs">
                <thead className="table-head"><tr><th className="px-3 py-2">Máquina</th><th className="px-3 py-2">Zona</th><th className="px-3 py-2 text-right">Utilización</th><th className="px-3 py-2 text-right">USD/h</th><th className="px-3 py-2">Clase</th></tr></thead>
                <tbody className="divide-y divide-hairline">
                  {[...prod.data].sort((a, b) => b.utilization_pct - a.utilization_pct).map((p) => (
                    <tr key={p.machine_id}>
                      <td className="px-3 py-2 font-mono font-semibold">{p.machine_id}</td>
                      <td className="px-3 py-2 capitalize text-on-surface-variant">{p.zone}</td>
                      <td className="px-3 py-2 text-right font-mono">{fmt1(p.utilization_pct)}%</td>
                      <td className="px-3 py-2 text-right font-mono">{fmt1(p.cost_per_hour_usd)}</td>
                      <td className="px-3 py-2">{CLASS_LABEL[p.classification]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </section>

      <Panel icon="swap_horiz" iconTone="secondary" title="Sugerencias de redistribución" subtitle="Equilibrar máquinas sobreexplotadas y subutilizadas" bodyClassName="p-0">
        {suggestions.length === 0 ? (
          <Empty icon="balance" title="La carga está equilibrada" />
        ) : (
          <ul className="grid grid-cols-1 divide-y divide-hairline md:grid-cols-2 md:divide-y-0">
            {suggestions.slice(0, 10).map((p) => (
              <li key={p.machine_id} className="flex items-center gap-3 border-hairline px-5 py-3 md:border-b">
                <Badge tone="warn">{fmt1(p.utilization_pct)}%</Badge>
                <span className="font-mono text-sm font-semibold text-on-surface">{p.machine_id}</span>
                <span className="flex-1 text-xs text-on-surface-variant">{p.redistribution_suggestion}</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </>
  );
}

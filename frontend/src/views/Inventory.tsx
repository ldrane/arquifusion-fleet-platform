import { useMemo } from "react";
import { Link } from "react-router-dom";
import type { InventoryItem, MaintenancePlanItem } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { can } from "@/auth/permissions";
import { Badge, cx, Empty, ErrorBox, Icon, KpiCard, Loading, Panel, Segmented } from "@/components/ui";
import { COMPONENT_BY_ID, SEED } from "@/demo/data";
import { fmt1, fmtDate, fmtUsd, SPECIALTY_LABEL } from "@/lib/format";
import { api } from "@/services";
import { useFleet } from "@/state/FleetContext";
import { useQuery } from "@/state/queryCache";
import { useViewState } from "@/state/viewState";

type Tab = "stock" | "forecast" | "ranking" | "plan";

function StockBar({ item }: { item: InventoryItem }) {
  const max = Math.max(item.stock_max * 1.2, item.stock, 1);
  const tone = item.alert === "low_stock" ? "bg-error" : item.alert === "overstock" ? "bg-tertiary" : "bg-secondary";
  return (
    <div className="relative h-2 w-32 rounded-full bg-surface-container-highest" title={`min ${item.stock_min} · max ${item.stock_max}`}>
      <div className={cx("h-full rounded-full", tone)} style={{ width: `${(item.stock / max) * 100}%` }} />
      <span className="absolute top-[-2px] h-3 w-px bg-on-surface-variant" style={{ left: `${(item.stock_min / max) * 100}%` }} />
      <span className="absolute top-[-2px] h-3 w-px bg-on-surface-variant" style={{ left: `${(item.stock_max / max) * 100}%` }} />
    </div>
  );
}

const ALERT_BADGE = {
  low_stock: <Badge tone="bad">Bajo mínimo</Badge>,
  overstock: <Badge tone="warn">Sobrestock</Badge>,
  none: <Badge tone="good">OK</Badge>,
};

const FLAG_BADGE: Record<MaintenancePlanItem["flag"], JSX.Element> = {
  overdue: <Badge tone="bad">Vencido</Badge>,
  unnecessary: <Badge tone="info">Postergable</Badge>,
  on_track: <Badge tone="good">En plan</Badge>,
};

export function Inventory() {
  const { role } = useAuth();
  const { zone } = useFleet();
  const [savedTab, setTab] = useViewState<Tab>("inv.tab", "stock");
  const [wh, setWh] = useViewState("inv.warehouse", "");
  const [alert, setAlert] = useViewState<"" | "low_stock" | "overstock">("inv.alert", "");
  const [horizon, setHorizon] = useViewState<"7" | "30" | "90">("inv.horizon", "30");
  const [flag, setFlag] = useViewState<"" | "overdue" | "unnecessary">("inv.flag", "");
  const [search, setSearch] = useViewState("inv.search", "");

  const inventory = useQuery("inventory:all", () => api.listInventory(), { staleMs: 10_000, refreshMs: 20_000 });
  const forecast = useQuery(can(role, "partsForecast") ? `forecast:${horizon}` : null, () => api.partsForecast({ horizon_days: Number(horizon) as 7 | 30 | 90 }), { staleMs: 30_000 });
  const ranking = useQuery(can(role, "partsRanking") ? "parts:ranking" : null, () => api.partsRanking(), { staleMs: 60_000 });
  const plan = useQuery(can(role, "maintenancePlan") ? `plan:${zone}` : null, () => api.maintenancePlan(zone ? { zone } : {}), { staleMs: 30_000 });

  const items = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (inventory.data ?? []).filter(
      (i) => (!wh || i.warehouse_id === wh) && (!alert || i.alert === alert) && (!q || i.name.toLowerCase().includes(q) || i.component_id.toLowerCase().includes(q)),
    );
  }, [inventory.data, wh, alert, search]);
  const low = (inventory.data ?? []).filter((i) => i.alert === "low_stock");
  const over = (inventory.data ?? []).filter((i) => i.alert === "overstock");
  const value = (inventory.data ?? []).reduce((a, i) => a + i.stock * (COMPONENT_BY_ID.get(i.component_id)?.cost_usd ?? 0), 0);
  const shortages = (forecast.data ?? []).filter((f) => f.shortage_for_planned_maintenance);
  const overdue = (plan.data ?? []).filter((p) => p.flag === "overdue");
  const postponable = (plan.data ?? []).filter((p) => p.flag === "unnecessary");

  const tabs: { value: Tab; label: string }[] = [
    { value: "stock", label: "Stock" },
    ...(can(role, "partsForecast") ? [{ value: "forecast" as Tab, label: "Pronóstico" }] : []),
    ...(can(role, "partsRanking") ? [{ value: "ranking" as Tab, label: "Ranking" }] : []),
    ...(can(role, "maintenancePlan") ? [{ value: "plan" as Tab, label: "Plan preventivo" }] : []),
  ];
  // La pestaña guardada puede no estar permitida para el rol actual (cambio de usuario)
  const tab: Tab = tabs.some((t) => t.value === savedTab) ? savedTab : "stock";

  return (
    <>
      <section className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <KpiCard label="Bajo stock mínimo" tone={low.length ? "bad" : "good"} value={low.length} unit="ítems" description={low.slice(0, 2).map((i) => i.name).join(" · ") || "Todo sobre el mínimo"} />
        <KpiCard label="Sobrestock" tone={over.length ? "warn" : "good"} value={over.length} unit="ítems" description="Capital inmovilizado sobre el máximo" />
        <KpiCard label="Faltante para preventivos" tone={shortages.length ? "warn" : "good"} value={can(role, "partsForecast") ? shortages.length : "—"} unit={`a ${horizon} días`} description="Demanda esperada mayor que el stock" />
        <KpiCard label="Valor del inventario" tone="info" value={fmtUsd(value)} description={`${SEED.warehouses.length} almacenes · ${SEED.catalog.length} componentes`} />
      </section>

      <Panel
        icon="inventory_2"
        iconTone="tertiary"
        title="Inventario y repuestos"
        subtitle="GET /inventory · /parts/forecast · /parts/ranking · /maintenance/plan"
        bodyClassName="p-0"
        actions={<Segmented label="Sección" value={tab} onChange={setTab} options={tabs} />}
      >
        {tab === "stock" && (
          <>
            <div className="flex flex-wrap items-center gap-2 border-b border-outline-variant/20 px-5 py-3">
              <input className="input w-48 py-1.5 text-xs" placeholder="Buscar componente" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Buscar componente" />
              <select className="input w-auto py-1.5 text-xs" value={wh} onChange={(e) => setWh(e.target.value)} aria-label="Almacén">
                <option value="">Todos los almacenes</option>
                {SEED.warehouses.map((w) => <option key={w.warehouse_id} value={w.warehouse_id}>{w.warehouse_id} · {w.name}</option>)}
              </select>
              <select className="input w-auto py-1.5 text-xs" value={alert} onChange={(e) => setAlert(e.target.value as typeof alert)} aria-label="Alerta">
                <option value="">Todas las alertas</option>
                <option value="low_stock">Bajo mínimo</option>
                <option value="overstock">Sobrestock</option>
              </select>
            </div>
            {inventory.error ? (
              <div className="p-5"><ErrorBox error={inventory.error} onRetry={inventory.refetch} /></div>
            ) : inventory.loading ? (
              <Loading />
            ) : items.length === 0 ? (
              <Empty icon="search_off" title="Sin ítems para estos filtros" />
            ) : (
              <div className="max-h-[560px] overflow-auto scroll-thin">
                <table className="w-full min-w-[720px] text-left text-sm">
                  <thead className="table-head">
                    <tr><th className="px-4 py-2.5">Componente</th><th className="px-4 py-2.5">Almacén</th><th className="px-4 py-2.5">Especialidad</th><th className="px-4 py-2.5 text-right">Stock</th><th className="px-4 py-2.5">Rango min–max</th><th className="px-4 py-2.5">Estado</th></tr>
                  </thead>
                  <tbody className="divide-y divide-outline-variant/15">
                    {items.map((i) => {
                      const c = COMPONENT_BY_ID.get(i.component_id);
                      return (
                        <tr key={`${i.warehouse_id}-${i.component_id}`} className="hover:bg-surface-container">
                          <td className="px-4 py-2.5"><span className="font-mono text-xs text-outline">{i.component_id}</span> <span className="text-on-surface">{i.name}</span></td>
                          <td className="px-4 py-2.5 font-mono text-xs text-on-surface-variant">{i.warehouse_id}</td>
                          <td className="px-4 py-2.5 text-xs text-on-surface-variant">{c ? SPECIALTY_LABEL[c.specialty] : "—"}</td>
                          <td className="px-4 py-2.5 text-right font-mono font-semibold text-on-surface">{i.stock}</td>
                          <td className="px-4 py-2.5"><div className="flex items-center gap-2"><StockBar item={i} /><span className="font-mono text-[11px] text-outline">{i.stock_min}–{i.stock_max}</span></div></td>
                          <td className="px-4 py-2.5">{ALERT_BADGE[i.alert]}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        {tab === "forecast" && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-outline-variant/20 px-5 py-3">
              <Segmented label="Horizonte" value={horizon} onChange={setHorizon} options={[{ value: "7", label: "7 d" }, { value: "30", label: "30 d" }, { value: "90", label: "90 d" }]} />
              <span className="text-xs text-on-surface-variant">Mín/máx recomendados según lead time y preventivos programados (AnalisisDiario · rama repuestos)</span>
            </div>
            {forecast.error ? <div className="p-5"><ErrorBox error={forecast.error} onRetry={forecast.refetch} /></div> : !forecast.data ? <Loading /> : (
              <div className="max-h-[560px] overflow-auto scroll-thin">
                <table className="w-full min-w-[720px] text-left text-sm">
                  <thead className="table-head"><tr><th className="px-4 py-2.5">Componente</th><th className="px-4 py-2.5">Almacén</th><th className="px-4 py-2.5 text-right">Demanda esperada</th><th className="px-4 py-2.5 text-right">Stock</th><th className="px-4 py-2.5 text-right">Mín / máx recomendado</th><th className="px-4 py-2.5">Preventivos</th></tr></thead>
                  <tbody className="divide-y divide-outline-variant/15">
                    {[...forecast.data].sort((a, b) => Number(b.shortage_for_planned_maintenance) - Number(a.shortage_for_planned_maintenance) || b.expected_demand - a.expected_demand).map((f) => (
                      <tr key={`${f.warehouse_id}-${f.component_id}`} className="hover:bg-surface-container">
                        <td className="px-4 py-2.5"><span className="font-mono text-xs text-outline">{f.component_id}</span> {COMPONENT_BY_ID.get(f.component_id)?.name}</td>
                        <td className="px-4 py-2.5 font-mono text-xs text-on-surface-variant">{f.warehouse_id}</td>
                        <td className="px-4 py-2.5 text-right font-mono">{fmt1(f.expected_demand)}</td>
                        <td className={cx("px-4 py-2.5 text-right font-mono font-semibold", f.stock < f.recommended_min ? "text-error" : "text-on-surface")}>{f.stock}</td>
                        <td className="px-4 py-2.5 text-right font-mono text-on-surface-variant">{f.recommended_min} / {f.recommended_max}</td>
                        <td className="px-4 py-2.5">{f.shortage_for_planned_maintenance ? <Badge tone="bad">Faltante</Badge> : <Badge tone="good">Cubierto</Badge>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        {tab === "ranking" && (
          ranking.error ? <div className="p-5"><ErrorBox error={ranking.error} onRetry={ranking.refetch} /></div> : !ranking.data ? <Loading /> : (
            <ol className="divide-y divide-outline-variant/15">
              {ranking.data.slice(0, 15).map((p, idx) => {
                const max = ranking.data![0]?.units_used_90d || 1;
                return (
                  <li key={p.component_id} className="flex items-center gap-4 px-5 py-2.5">
                    <span className="w-6 font-mono text-xs text-outline">{idx + 1}</span>
                    <span className="w-64 truncate text-sm text-on-surface"><span className="font-mono text-xs text-outline">{p.component_id}</span> {p.name}</span>
                    <div className="h-2 flex-1 rounded-full bg-surface-container-highest">
                      <div className="h-full rounded-full bg-[#3987e5]" style={{ width: `${(p.units_used_90d / max) * 100}%` }} />
                    </div>
                    <span className="w-16 text-right font-mono text-sm font-semibold text-on-surface">{p.units_used_90d}</span>
                    <span className="w-28 text-right">{p.irregular_consumption ? <Badge tone="warn">Irregular</Badge> : null}</span>
                  </li>
                );
              })}
            </ol>
          )
        )}

        {tab === "plan" && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-outline-variant/20 px-5 py-3">
              <Segmented label="Filtro" value={flag} onChange={setFlag} options={[{ value: "", label: `Todos (${plan.data?.length ?? 0})` }, { value: "overdue", label: `Vencidos (${overdue.length})` }, { value: "unnecessary", label: `Postergables (${postponable.length})` }]} />
              <span className="text-xs text-on-surface-variant">Priorizado por condición, no solo por calendario (RF-03)</span>
            </div>
            {plan.error ? <div className="p-5"><ErrorBox error={plan.error} onRetry={plan.refetch} /></div> : !plan.data ? <Loading /> : (
              <div className="max-h-[560px] overflow-auto scroll-thin">
                <table className="w-full min-w-[720px] text-left text-sm">
                  <thead className="table-head"><tr><th className="px-4 py-2.5">#</th><th className="px-4 py-2.5">Máquina</th><th className="px-4 py-2.5">Zona</th><th className="px-4 py-2.5">Próximo</th><th className="px-4 py-2.5">Estado</th><th className="px-4 py-2.5">Motivo</th></tr></thead>
                  <tbody className="divide-y divide-outline-variant/15">
                    {plan.data.filter((p) => !flag || p.flag === flag).slice(0, 100).map((p) => (
                      <tr key={p.machine_id} className="hover:bg-surface-container">
                        <td className="px-4 py-2.5 font-mono text-xs text-outline">{p.priority}</td>
                        <td className="px-4 py-2.5 font-mono font-semibold"><Link to={`/salud/${p.machine_id}`} className="text-on-surface hover:text-primary">{p.machine_id}</Link></td>
                        <td className="px-4 py-2.5 font-mono text-xs capitalize text-on-surface-variant">{p.zone}</td>
                        <td className="px-4 py-2.5 font-mono text-xs text-on-surface-variant">{fmtDate(p.next_maintenance_at)}</td>
                        <td className="px-4 py-2.5">{FLAG_BADGE[p.flag]}</td>
                        <td className="px-4 py-2.5 text-xs text-on-surface-variant">{p.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </Panel>
      <p className="flex items-center gap-2 text-xs text-outline">
        <Icon name="info" className="text-[16px]" />
        El inventario se descuenta automáticamente al cerrar un incidente con componentes reemplazados (GestionIncidente → cierre).
      </p>
    </>
  );
}

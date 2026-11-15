import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { Incident } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { can } from "@/auth/permissions";
import { IncidentCard } from "@/components/incidents/IncidentCard";
import { FleetMap, type MapFilter } from "@/components/map/FleetMap";
import { Badge, Button, cx, Empty, HealthBar, Icon, KpiCard, Panel, Segmented, StatusDot } from "@/components/ui";
import { SEED } from "@/demo/data";
import { SEVERITY_RANK, STATUS_LABEL, TYPE_LABEL, ZONE_LABEL, timeAgo } from "@/lib/format";
import { myTechnicianId } from "@/lib/ids";
import { api } from "@/services";
import { useZoned } from "@/state/FleetContext";
import { useQuery } from "@/state/queryCache";
import { useViewState } from "@/state/viewState";

const OPEN = (i: Incident) => i.status !== "closed" && !i.parent_incident_id;

export function CommandCenter() {
  const { me } = useAuth();
  const { machines, incidents, technicians, zone } = useZoned();
  const navigate = useNavigate();
  const [filter, setFilter] = useViewState<MapFilter>("cc.mapFilter", "all");
  const [sort, setSort] = useViewState<"severity" | "age">("cc.sort", "severity");
  const [selected, setSelected] = useViewState<string | null>("cc.selected", null);
  const inventory = useQuery(can(me?.role, "inventory") ? "inventory:low" : null, () => api.listInventory({ alert: "low_stock" }), { staleMs: 30_000 });

  const open = useMemo(() => {
    const xs = incidents.filter(OPEN);
    return xs.sort((a, b) =>
      sort === "severity"
        ? SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || a.detected_at.localeCompare(b.detected_at)
        : b.detected_at.localeCompare(a.detected_at),
    );
  }, [incidents, sort]);

  const myTech = myTechnicianId(me);
  const queue = me?.role === "tecnico" ? [...open.filter((i) => i.assigned_technician_id === myTech), ...open.filter((i) => i.assigned_technician_id !== myTech)] : open;

  const active = machines.filter((m) => m.status === "operational").length;
  const availability = machines.length ? (active / machines.length) * 100 : 0;
  const critical = open.filter((i) => i.severity === "critical" || i.severity === "high");
  const atRisk = machines.filter((m) => m.health_score < 70).length;
  const silent = machines.filter((m) => m.status === "silent").length;
  const freeTechs = technicians.filter((t) => t.available);
  const busyTechs = technicians.filter((t) => !t.available);
  const counts = {
    critical: machines.filter((m) => m.severity === "critical" || m.severity === "high").length,
    warning: machines.filter((m) => m.severity === "medium" || m.severity === "low").length,
    ok: machines.filter((m) => m.severity === "info" && m.status === "operational").length,
  };
  const banner = open.find((i) => i.child_incident_ids.length > 0) ?? open.find((i) => i.severity === "critical");
  const usdProtected = useMemo(() => {
    const cutoff = Date.now() - 30 * 86_400_000;
    return incidents
      .filter((i) => i.status === "closed" && i.closed_at && new Date(i.closed_at).getTime() >= cutoff)
      .reduce((a, i) => a + (i.value_protected_usd ?? 0), 0);
  }, [incidents]);
  const sel = machines.find((m) => m.machine_id === selected);
  const selIncident = sel?.open_incident_id ? incidents.find((i) => i.incident_id === sel.open_incident_id) : undefined;
  const lowStock = inventory.data ?? [];

  return (
    <>
      <section className="stagger grid w-full grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Disponibilidad flota"
          tone="good"
          badge={<Badge tone={availability >= 92 ? "good" : "warn"} pulse>{availability >= 92 ? "Óptimo" : "Bajo meta"}</Badge>}
          value={`${availability.toFixed(1)}%`}
          description={`${active} de ${machines.length} unidades operativas · ${ZONE_LABEL(zone || me?.zone)}`}
          footer={
            <>
              <span>Meta turno: 92.0%</span>
              <span className={atRisk ? "font-medium text-tertiary" : "font-medium text-secondary"}>{atRisk} en riesgo</span>
            </>
          }
        />
        <KpiCard
          label="Alertas críticas"
          tone="bad"
          badge={critical.length ? <Badge tone="bad" pulse>{critical.length} activas</Badge> : <Badge tone="good">Sin críticas</Badge>}
          value={critical.length}
          unit="requieren triaje"
          description={<span className="block truncate">{critical.slice(0, 2).map((i) => i.ai_diagnosis?.probable_cause ?? i.machine_ids[0]).join(" • ") || "Flota sin alertas altas"}</span>}
          footer={
            <>
              <span>{open.length} incidentes abiertos</span>
              <Link to="/incidentes" className="flex items-center gap-1 font-semibold text-primary hover:underline">
                Ver incidentes <Icon name="arrow_forward" className="text-[14px]" />
              </Link>
            </>
          }
        />
        {technicians.length > 0 ? (
          <KpiCard
            label="Técnicos de campo"
            tone="info"
            badge={<Badge tone="info">{freeTechs.length ? "Listos" : "Saturados"}</Badge>}
            value={freeTechs.length}
            unit="disponibles"
            description={`${busyTechs.length} en atención · ${technicians.length} en turno`}
            footer={
              <>
                <span>{open.filter((i) => i.status === "assigned").length} esperando ack</span>
                {can(me?.role, "technicians") ? (
                  <Link to="/despacho" className="font-medium text-primary hover:underline">
                    Despacho
                  </Link>
                ) : (
                  <span />
                )}
              </>
            }
          />
        ) : (
          <KpiCard
            label="Telemetría"
            tone={silent ? "warn" : "good"}
            badge={<Badge tone={silent ? "warn" : "good"}>{silent ? "Revisar" : "Estable"}</Badge>}
            value={machines.length - silent}
            unit="reportando"
            description={`${silent} máquinas sin señal (heartbeat cada 5 min)`}
            footer={<span>Intervalo esperado: 30 s</span>}
          />
        )}
        {can(me?.role, "inventory") ? (
          <KpiCard
            label="Repuestos en riesgo"
            tone="warn"
            badge={<Badge tone={lowStock.length ? "warn" : "good"}>{lowStock.length ? `${lowStock.length} bajo stock` : "Cubierto"}</Badge>}
            value={inventory.loading ? "…" : lowStock.length}
            unit="bajo mínimo"
            description={<span className="block truncate">{lowStock.slice(0, 2).map((i) => `${i.name} (${i.warehouse_id})`).join(" · ") || "Inventario sobre el mínimo"}</span>}
            footer={
              <>
                <span>{SEED.warehouses.length} almacenes</span>
                <Link to="/inventario" className="font-medium text-tertiary hover:underline">
                  Ver inventario
                </Link>
              </>
            }
          />
        ) : (
          <KpiCard
            label="Salud media de la flota"
            tone={atRisk > 5 ? "warn" : "good"}
            badge={<Badge tone="info">Predictivo</Badge>}
            value={machines.length ? Math.round(machines.reduce((a, m) => a + m.health_score, 0) / machines.length) : "—"}
            unit="/ 100"
            description={`${atRisk} máquinas con health < 70`}
            footer={
              <Link to="/salud" className="font-medium text-primary hover:underline">
                Salud predictiva
              </Link>
            }
          />
        )}
        <KpiCard
          label="USD protegidos (30 d)"
          tone="good"
          badge={<Badge tone="good">Valor</Badge>}
          value={`$${Math.round(usdProtected).toLocaleString("es-PE")}`}
          unit="paro evitado"
          description={
            <span className="block truncate" title="Supuestos: paro esperado por severidad × costo/h del modelo">
              Cierre real vs. paro esperado por severidad
            </span>
          }
          footer={<span>Supuestos: baseline por severidad × costo/h del modelo</span>}
        />
      </section>

      <section className="stagger grid w-full grid-cols-1 items-start gap-5 xl:grid-cols-12">
        <Panel
          className="xl:col-span-7"
          icon="radar"
          title={`Mapa de operaciones — ${ZONE_LABEL(zone || me?.zone)}`}
          subtitle="OP-01 · sierra central · posiciones en vivo"
          bodyClassName="p-0"
          actions={
            <Segmented
              label="Filtro del mapa"
              value={filter}
              onChange={setFilter}
              options={[
                { value: "all", label: `Todos (${machines.length})` },
                { value: "critical", label: <><span className="h-1.5 w-1.5 rounded-full bg-error" />Críticos ({counts.critical + silent})</> },
                { value: "techs", label: <><span className="h-1.5 w-1.5 rounded-full bg-primary" />Técnicos ({technicians.length})</> },
              ]}
            />
          }
        >
          <div className="relative">
            {banner && (
              <div className="absolute left-4 right-4 top-4 z-[500] flex flex-wrap items-center justify-between gap-3 rounded-xl border border-error/30 bg-surface-container/90 px-4 py-3 shadow-pop backdrop-blur-md">
                <div className="flex min-w-0 items-center gap-3">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-error/15 text-error">
                    <Icon name="warning" />
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs font-semibold uppercase text-on-surface tracking-[0.06em]">
                        {banner.child_incident_ids.length ? `Alerta grupal · zona ${banner.zone}` : `Alerta crítica · ${banner.machine_ids[0]}`}
                      </span>
                      <span className="rounded-full bg-error px-2 py-0.5 font-mono text-[10px] font-semibold text-on-error">{banner.incident_id}</span>
                    </div>
                    <span className="block truncate text-xs text-on-surface-variant">
                      {banner.ai_diagnosis?.probable_cause ?? "Diagnóstico IA en curso"} · {banner.machine_ids.length} máquina(s) · {timeAgo(banner.detected_at)}
                    </span>
                  </div>
                </div>
                <Button variant="danger" icon="open_in_new" onClick={() => navigate(`/incidentes/${banner.incident_id}`)}>
                  Atender
                </Button>
              </div>
            )}
            <FleetMap
              machines={machines}
              technicians={technicians}
              incidents={incidents}
              filter={filter}
              zone={zone}
              selectedId={selected}
              onSelect={setSelected}
              className="h-[540px] w-full"
            />
            {sel && (
              <div key={sel.machine_id} className="rise absolute bottom-4 left-4 right-4 z-[500] flex flex-wrap items-center justify-between gap-3 rounded-xl bg-surface-container/85 p-3 shadow-pop backdrop-blur-xl sm:right-auto sm:w-96">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm font-semibold text-on-surface">{sel.machine_id}</span>
                    <span className="font-mono text-[11px] text-outline">{sel.model} · {TYPE_LABEL[sel.type]}</span>
                  </div>
                  <div className="mt-1 flex items-center gap-3">
                    <StatusDot status={sel.status} />
                    <HealthBar value={sel.health_score} compact />
                  </div>
                  {selIncident && <div className="mt-1 truncate text-[11px] text-error">{selIncident.incident_id}: {selIncident.ai_diagnosis?.probable_cause ?? STATUS_LABEL[sel.status]}</div>}
                </div>
                <div className="flex gap-1">
                  <Button size="sm" variant="primary" icon="monitor_heart" onClick={() => navigate(`/salud/${sel.machine_id}`)}>
                    Detalle
                  </Button>
                  <button type="button" className="rounded-full p-1.5 text-outline hover:bg-surface-container" onClick={() => setSelected(null)} aria-label="Cerrar">
                    <Icon name="close" className="text-[18px]" />
                  </button>
                </div>
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-hairline bg-surface-container px-5 py-3 font-mono text-xs text-on-surface-variant">
            <div className="flex flex-wrap items-center gap-4">
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-error" />Crítico/alto ({counts.critical})</span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-tertiary" />Advertencia ({counts.warning})</span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-secondary" />Operativo ({counts.ok})</span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-idle" />Sin señal ({silent})</span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-primary" />Técnicos ({technicians.length})</span>
            </div>
            <span className="text-[11px] text-outline">Mapa base: Esri · capa oscura o satélite</span>
          </div>
        </Panel>

        <div className="flex flex-col gap-4 xl:col-span-5" id="incidentes">
          <div className="flex items-center justify-between rounded-xl border border-hairline bg-surface-container-low p-4">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-error/15 text-error">
                <Icon name="warning" className="text-[18px]" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-on-surface">{me?.role === "tecnico" ? "Mis asignaciones y cola" : "Incidentes y triaje prioritario"}</h2>
                <span className="text-xs font-medium text-secondary">GestionIncidente · {open.length} abiertos</span>
              </div>
            </div>
            <label className="flex items-center gap-1 rounded-full border border-hairline bg-surface-container px-3 py-1 font-mono text-xs text-on-surface-variant">
              <span className="sr-only">Ordenar</span>
              <select className="cursor-pointer bg-transparent focus:outline-none" value={sort} onChange={(e) => setSort(e.target.value as "severity" | "age")}>
                <option className="bg-surface-container-high" value="severity">Por severidad</option>
                <option className="bg-surface-container-high" value="age">Más recientes</option>
              </select>
            </label>
          </div>
          {queue.length === 0 && (
            <div className="panel">
              <Empty icon="verified" title="Sin incidentes abiertos">La flota opera sin anomalías que requieran triaje.</Empty>
            </div>
          )}
          {queue.slice(0, 4).map((i) => (
            <div key={i.incident_id} className={cx(me?.role === "tecnico" && i.assigned_technician_id === myTech && "rounded-xl ring-1 ring-primary/40")}>
              <IncidentCard incident={i} machine={machines.find((m) => m.machine_id === i.machine_ids[0])} technician={technicians.find((t) => t.technician_id === i.assigned_technician_id)} />
            </div>
          ))}
          {queue.length > 4 && (
            <Link to="/incidentes" className="text-center text-xs font-semibold text-primary hover:underline">
              Ver los {queue.length} incidentes abiertos →
            </Link>
          )}
        </div>
      </section>
    </>
  );
}

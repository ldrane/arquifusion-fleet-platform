import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import type { IncidentStatus, Severity } from "@/api/types";
import { Button, Empty, Icon, IncidentStatusBadge, KpiCard, Panel, SeverityBadge } from "@/components/ui";
import { fmt1, fmtDateTime, fmtUsd, INCIDENT_STATUS_LABEL, SEVERITY_LABEL, SEVERITY_RANK } from "@/lib/format";
import { useZoned } from "@/state/FleetContext";
import { useViewState } from "@/state/viewState";

const PAGE = 25;

function toCsv(rows: (string | number | null)[][]) {
  return rows.map((r) => r.map((v) => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
}

export function IncidentHistory() {
  const { incidents, technicians } = useZoned();
  const navigate = useNavigate();
  const [status, setStatus] = useViewState<IncidentStatus | "" | "open">("hist.status", "");
  const [severity, setSeverity] = useViewState<Severity | "">("hist.severity", "");
  const [search, setSearch] = useViewState("hist.search", "");
  const [page, setPage] = useViewState("hist.page", 0);

  const rows = useMemo(() => {
    const q = search.trim().toUpperCase();
    return incidents
      .filter((i) => !i.parent_incident_id)
      .filter(
        (i) =>
          (!status || (status === "open" ? i.status !== "closed" : i.status === status)) &&
          (!severity || i.severity === severity) &&
          (!q || i.incident_id.includes(q) || i.machine_ids.some((m) => m.includes(q)) || (i.assigned_technician_id ?? "").includes(q)),
      )
      .sort((a, b) => Number(a.status === "closed") - Number(b.status === "closed") || b.detected_at.localeCompare(a.detected_at) || SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity]);
  }, [incidents, status, severity, search]);

  const closed = incidents.filter((i) => i.status === "closed" && !i.parent_incident_id);
  const mttr = closed.length ? closed.reduce((a, i) => a + (i.downtime_minutes ?? 0), 0) / closed.length / 60 : 0;
  const cost = closed.reduce((a, i) => a + (i.cost_usd ?? 0), 0);
  const recurrent = closed.filter((i) => i.is_recurrence).length;
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const current = Math.min(page, pages - 1);
  const techName = (id: string | null) => technicians.find((t) => t.technician_id === id)?.name ?? id ?? "—";

  const exportCsv = () => {
    const csv = toCsv([
      ["incident_id", "machine_ids", "zone", "severity", "status", "technician", "detected_at", "resolved_at", "downtime_minutes", "cost_usd", "probable_cause"],
      ...rows.map((i) => [i.incident_id, i.machine_ids.join(" "), i.zone, i.severity, i.status, i.assigned_technician_id, i.detected_at, i.resolved_at, i.downtime_minutes, i.cost_usd, i.ai_diagnosis?.probable_cause ?? ""]),
    ]);
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `incidentes-${new Date().toISOString().slice(0, 10)}.csv` });
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <section className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <KpiCard label="Abiertos" tone={incidents.some((i) => i.status !== "closed") ? "bad" : "good"} value={incidents.filter((i) => i.status !== "closed" && !i.parent_incident_id).length} unit="en curso" />
        <KpiCard label="Cerrados" tone="info" value={closed.length} unit="histórico" description={`${recurrent} recurrentes (misma máquina)`} />
        <KpiCard label="MTTR medio" tone="neutral" value={fmt1(mttr)} unit="h" description="De la detección a la resolución" />
        <KpiCard label="Costo correctivo" tone="warn" value={fmtUsd(cost)} description="Repuestos + mano de obra" />
      </section>

      <Panel
        icon="history_toggle_off"
        title="Historial de incidentes"
        subtitle="GET /v1/incidents · réplica en vivo"
        bodyClassName="p-0"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <input className="input w-44 py-1.5 font-mono text-xs" placeholder="INC, máquina o TEC" value={search} onChange={(e) => { setSearch(e.target.value); setPage(0); }} aria-label="Buscar incidente" />
            <select className="input w-auto py-1.5 text-xs" value={status} onChange={(e) => { setStatus(e.target.value as typeof status); setPage(0); }} aria-label="Estado">
              <option value="">Todos los estados</option>
              <option value="open">Solo abiertos</option>
              {Object.entries(INCIDENT_STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <select className="input w-auto py-1.5 text-xs" value={severity} onChange={(e) => { setSeverity(e.target.value as Severity | ""); setPage(0); }} aria-label="Severidad">
              <option value="">Toda severidad</option>
              {Object.entries(SEVERITY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <Button size="sm" icon="download" onClick={exportCsv} disabled={!rows.length}>CSV</Button>
          </div>
        }
      >
        {rows.length === 0 ? (
          <Empty icon="search_off" title="Sin incidentes para estos filtros" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[880px] text-left text-sm">
              <thead className="table-head">
                <tr><th className="px-4 py-2.5">Incidente</th><th className="px-4 py-2.5">Máquina(s)</th><th className="px-4 py-2.5">Severidad</th><th className="px-4 py-2.5">Estado</th><th className="px-4 py-2.5">Causa probable (IA)</th><th className="px-4 py-2.5">Técnico</th><th className="px-4 py-2.5">Detectado</th><th className="px-4 py-2.5 text-right">MTTR</th></tr>
              </thead>
              <tbody className="divide-y divide-outline-variant/15">
                {rows.slice(current * PAGE, current * PAGE + PAGE).map((i) => (
                  <tr key={i.incident_id} className="cursor-pointer hover:bg-surface-container" onClick={() => navigate(`/incidentes/${i.incident_id}`)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && navigate(`/incidentes/${i.incident_id}`)}>
                    <td className="px-4 py-2.5 font-mono text-xs font-semibold text-on-surface">
                      {i.incident_id}
                      {i.child_incident_ids.length > 0 && <span className="ml-1 rounded bg-primary/15 px-1 text-[10px] text-primary">grupal</span>}
                      {i.escalated && <Icon name="trending_up" className="ml-1 align-middle text-[14px] text-error" />}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-on-surface-variant">{i.machine_ids.join(", ")}</td>
                    <td className="px-4 py-2.5"><SeverityBadge severity={i.severity} /></td>
                    <td className="px-4 py-2.5"><IncidentStatusBadge status={i.status} /></td>
                    <td className="max-w-xs truncate px-4 py-2.5 text-xs text-on-surface-variant">{i.ai_diagnosis?.probable_cause ?? "—"}</td>
                    <td className="px-4 py-2.5 text-xs text-on-surface-variant">{techName(i.assigned_technician_id)}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-on-surface-variant">{fmtDateTime(i.detected_at)}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs">{i.downtime_minutes != null ? `${i.downtime_minutes} min` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="flex items-center justify-between border-t border-outline-variant/20 px-5 py-2 font-mono text-[11px] text-outline">
          <span>{rows.length} incidentes</span>
          <span className="flex items-center gap-2">
            <Button size="sm" variant="ghost" icon="chevron_left" disabled={current === 0} onClick={() => setPage(current - 1)} aria-label="Página anterior" />
            {current + 1} / {pages}
            <Button size="sm" variant="ghost" icon="chevron_right" disabled={current >= pages - 1} onClick={() => setPage(current + 1)} aria-label="Página siguiente" />
          </span>
        </div>
      </Panel>
    </>
  );
}

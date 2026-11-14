import { useMemo, useState } from "react";
import { errorMessage } from "@/api/errors";
import type { Incident, Machine } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { can } from "@/auth/permissions";
import { COMPONENT_BY_ID, SEED } from "@/demo/data";
import { fmtUsd, SPECIALTY_LABEL } from "@/lib/format";
import { myTechnicianId } from "@/lib/ids";
import { scoreTechnicians } from "@/lib/scoring";
import { api } from "@/services";
import { invalidate, useQuery } from "@/state/queryCache";
import { useFleet } from "@/state/FleetContext";
import { Button, cx, Loading } from "../ui";
import { Modal } from "../ui/Modal";
import { useToast } from "../ui/Toast";

/** Acciones de comando sobre un incidente (POST /incidents/{id}/ack|assign|resolve), filtradas por rol. */
export function IncidentActions({ incident, compact }: { incident: Incident; compact?: boolean }) {
  const { me } = useAuth();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [dialog, setDialog] = useState<null | "assign" | "resolve" | "reject">(null);
  if (!me || incident.parent_incident_id || incident.status === "closed" || incident.status === "resolved") return null;

  const myTech = myTechnicianId(me);
  const mine = incident.assigned_technician_id != null && incident.assigned_technician_id === myTech;
  const canAck = can(me.role, "ack") && incident.status === "assigned" && (me.role !== "tecnico" || mine);
  const canResolve = can(me.role, "resolve") && incident.status === "in_progress" && (me.role !== "tecnico" || mine);
  const canAssign = can(me.role, "assign") && (incident.status === "detected" || incident.status === "assigned");

  const run = async (key: string, fn: () => Promise<Incident>, ok: string) => {
    setBusy(key);
    try {
      await fn();
      invalidate(`incident:${incident.incident_id}`);
      invalidate("incidents");
      toast(ok, "good");
      setDialog(null);
    } catch (e) {
      toast(errorMessage(e), "bad");
    } finally {
      setBusy(null);
    }
  };

  if (!canAck && !canResolve && !canAssign) return null;
  return (
    <div className={cx("flex flex-wrap items-center gap-2", compact ? "" : "pt-1")}>
      {canAck && (
        <>
          <Button variant="primary" icon="check" busy={busy === "accept"} className="flex-1" onClick={() => run("accept", () => api.ack(incident.incident_id, "accept"), `${incident.incident_id} aceptado: en atención`)}>
            Aceptar
          </Button>
          <Button variant="secondary" icon="close" onClick={() => setDialog("reject")}>
            Rechazar
          </Button>
        </>
      )}
      {canResolve && (
        <Button variant="success" icon="task_alt" className="flex-1" onClick={() => setDialog("resolve")}>
          Marcar resuelto
        </Button>
      )}
      {canAssign && (
        <Button variant={canAck ? "ghost" : "primary"} icon="person_check" className={canAck ? "" : "flex-1"} onClick={() => setDialog("assign")}>
          {incident.assigned_technician_id ? "Reasignar" : "Asignar"}
        </Button>
      )}

      {dialog === "reject" && (
        <RejectDialog
          busy={busy === "reject"}
          onClose={() => setDialog(null)}
          onSubmit={(reason) => run("reject", () => api.ack(incident.incident_id, "reject", reason), "Rechazado: Step Functions reasigna al siguiente candidato")}
        />
      )}
      {dialog === "resolve" && (
        <ResolveDialog
          incident={incident}
          busy={busy === "resolve"}
          onClose={() => setDialog(null)}
          onSubmit={(body) => run("resolve", () => api.resolve(incident.incident_id, body), "Resuelto: la IA genera el resumen y cierra el incidente")}
        />
      )}
      {dialog === "assign" && (
        <AssignDialog
          incident={incident}
          busy={busy === "assign"}
          onClose={() => setDialog(null)}
          onSubmit={(tech, reason) => run("assign", () => api.assign(incident.incident_id, tech, reason), `Reasignado a ${tech}`)}
        />
      )}
    </div>
  );
}

function RejectDialog({ busy, onClose, onSubmit }: { busy: boolean; onClose: () => void; onSubmit: (reason: string) => void }) {
  const [reason, setReason] = useState("");
  return (
    <Modal
      title="Rechazar asignación"
      open
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button variant="danger" icon="close" busy={busy} onClick={() => onSubmit(reason.trim())}>
            Rechazar
          </Button>
        </>
      }
    >
      <label className="flex flex-col gap-1">
        <span className="label">Motivo (opcional, máx. 300)</span>
        <textarea className="input min-h-24" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Estoy atendiendo otra parada en la zona sur" />
      </label>
    </Modal>
  );
}

function ResolveDialog({
  incident,
  busy,
  onClose,
  onSubmit,
}: {
  incident: Incident;
  busy: boolean;
  onClose: () => void;
  onSubmit: (b: { resolution_notes: string; components_replaced: string[]; cost_usd?: number }) => void;
}) {
  const { machines } = useFleet();
  const model = machines.find((m) => m.machine_id === incident.machine_ids[0])?.model;
  const suggested = useMemo(
    () => SEED.catalog.filter((c) => !model || c.compatible_models.includes(model)).sort((a, b) => a.component_id.localeCompare(b.component_id)),
    [model],
  );
  const [notes, setNotes] = useState("");
  const [parts, setParts] = useState<string[]>([]);
  const [cost, setCost] = useState("");
  const estimate = parts.reduce((a, c) => a + (COMPONENT_BY_ID.get(c)?.cost_usd ?? 0), 0);
  return (
    <Modal
      title={`Resolver ${incident.incident_id}`}
      open
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button
            variant="success"
            icon="task_alt"
            busy={busy}
            disabled={!notes.trim()}
            onClick={() => onSubmit({ resolution_notes: notes.trim(), components_replaced: parts, ...(cost ? { cost_usd: Number(cost) } : {}) })}
          >
            Confirmar resolución
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <label className="flex flex-col gap-1">
          <span className="label">Notas de resolución *</span>
          <textarea className="input min-h-24" maxLength={2000} required value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Qué se encontró y qué se hizo" />
        </label>
        <div className="flex flex-col gap-1">
          <span className="label">Componentes reemplazados</span>
          <div className="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto scroll-thin">
            {suggested.map((c) => {
              const on = parts.includes(c.component_id);
              return (
                <button
                  key={c.component_id}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setParts((p) => (on ? p.filter((x) => x !== c.component_id) : [...p, c.component_id]))}
                  className={cx("rounded-lg border px-2 py-1 text-left text-[11px]", on ? "border-primary bg-primary/15 text-primary" : "border-hairline text-on-surface-variant hover:border-outline")}
                >
                  <span className="font-mono">{c.component_id}</span> {c.name}
                </button>
              );
            })}
          </div>
        </div>
        <label className="flex flex-col gap-1">
          <span className="label">Costo total USD (opcional)</span>
          <input className="input font-mono" type="number" min={0} value={cost} onChange={(e) => setCost(e.target.value)} placeholder={estimate ? `Repuestos: ${fmtUsd(estimate)}` : "0"} />
        </label>
        <p className="text-xs text-on-surface-variant">Al confirmar, Step Functions reanuda con el resolve_token: resumen IA, MTTR, descuento de inventario y registro de mantenimiento.</p>
      </div>
    </Modal>
  );
}

function AssignDialog({ incident, busy, onClose, onSubmit }: { incident: Incident; busy: boolean; onClose: () => void; onSubmit: (tech: string, reason?: string) => void }) {
  const { machines } = useFleet();
  const machine: Machine | undefined = machines.find((m) => m.machine_id === incident.machine_ids[0]);
  const q = useQuery(`technicians:eta:${incident.machine_ids[0]}`, () => api.listTechnicians({ machine_id: incident.machine_ids[0] }), { staleMs: 5000 });
  const [selected, setSelected] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const specialty = incident.ai_diagnosis ? guessSpecialty(incident.ai_diagnosis.probable_cause) : null;
  const ranked = useMemo(
    () => (q.data && machine ? scoreTechnicians(q.data, { location: machine.location, severity: incident.severity, specialty }) : []),
    [q.data, machine, incident.severity, specialty],
  );
  return (
    <Modal
      title={`${incident.assigned_technician_id ? "Reasignar" : "Asignar"} ${incident.incident_id}`}
      open
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button variant="primary" icon="person_check" busy={busy} disabled={!selected} onClick={() => selected && onSubmit(selected, reason.trim() || undefined)}>
            Confirmar
          </Button>
        </>
      }
    >
      <p className="mb-3 text-xs text-on-surface-variant">
        Ranking con la fórmula de scoring-tecnicos (especialidad{specialty ? `: ${SPECIALTY_LABEL[specialty]}` : ""}, ETA, disponibilidad y carga).
      </p>
      {q.loading && <Loading />}
      <ul className="flex flex-col gap-1.5">
        {ranked.map((c, i) => {
          const t = q.data!.find((x) => x.technician_id === c.technician_id)!;
          const current = c.technician_id === incident.assigned_technician_id;
          return (
            <li key={c.technician_id}>
              <button
                type="button"
                disabled={current}
                onClick={() => setSelected(c.technician_id)}
                className={cx(
                  "flex w-full items-center gap-3 rounded-xl border p-2.5 text-left transition-colors disabled:opacity-50",
                  selected === c.technician_id ? "border-primary bg-primary/10" : "border-hairline hover:border-outline",
                )}
              >
                <span className="w-5 font-mono text-xs text-outline">{i + 1}</span>
                <span className="flex-1">
                  <span className="block text-sm font-semibold text-on-surface">
                    {t.name} <span className="font-mono text-[11px] text-outline">{t.technician_id}</span>
                    {current && <span className="ml-1 text-[11px] text-tertiary">(actual)</span>}
                  </span>
                  <span className="block text-[11px] text-on-surface-variant">
                    {t.specialties.map((s) => SPECIALTY_LABEL[s]).join(" · ")} · {t.available ? "disponible" : "ocupado"} · carga {t.current_load}
                  </span>
                </span>
                <span className="text-right font-mono text-xs">
                  <span className="block font-semibold text-primary">{c.score.toFixed(2)}</span>
                  <span className="text-outline">ETA {t.eta_minutes ?? c.eta_min} min</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <label className="mt-3 flex flex-col gap-1">
        <span className="label">Motivo (opcional)</span>
        <input className="input" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Especialista en hidráulica disponible" />
      </label>
    </Modal>
  );
}

/** Especialidad requerida inferida del diagnóstico (el contrato no la expone en Incident). */
export function guessSpecialty(cause: string) {
  const c = cause.toLowerCase();
  if (/hidr|manguera|válvula|valvula|sello/.test(c)) return "hidraulica" as const;
  if (/eléctr|electr|alternador|ecu|batería/.test(c)) return "electrica" as const;
  if (/neum|llanta|oruga/.test(c)) return "neumaticos" as const;
  return "motor" as const;
}

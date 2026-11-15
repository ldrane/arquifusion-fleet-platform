import type { Incident, Role } from "@/api/types";
import { COMPONENT_BY_ID, DEMO_USERS, SEED } from "@/demo/data";
import { fmtDateTime, ROLE_LABEL } from "@/lib/format";
import { Icon, Panel } from "../ui";

function personName(userId: string): string {
  const u = DEMO_USERS.find((x) => x.user_id === userId);
  const t = SEED.technicians.find((x) => x.user_id === userId || x.technician_id === userId);
  return u?.name ?? t?.name ?? userId;
}

/**
 * Cierre del incidente en dos bloques separados (RF-11.2, RF-16.8):
 *  1. "Resumen del chat (IA)": `resolution_summary` = summarize_chat sobre SOLO los mensajes del chat.
 *  2. "Notas de resolución": lo que escribió quien resolvió (POST /resolve), con autor y fecha.
 */
export function ClosureSummary({ incident: inc }: { incident: Incident }) {
  const closed = inc.status === "closed";
  const notes = inc.resolution_notes?.trim();
  const showNotes = Boolean(notes) || (closed && inc.components_replaced.length > 0);
  if (!closed && !showNotes) return null;
  const by = inc.resolved_by;
  const role = by?.role && by.role in ROLE_LABEL ? ROLE_LABEL[by.role as Role] : by?.role;
  const downtimeH = inc.downtime_h;
  const baselineH = inc.value_assumptions?.baseline_h;
  const avoidedH = downtimeH != null && baselineH != null ? Math.max(0, baselineH - downtimeH) : null;

  return (
    <>
      {closed && (
        <Panel icon="forum" iconTone="secondary" title="Resumen del chat (IA)" subtitle="summarize_chat · solo la conversación del canal">
          <p className="text-sm leading-relaxed text-on-surface" data-testid="chat-summary">
            {inc.resolution_summary?.trim() || "Sin resumen del chat."}
          </p>
          {downtimeH != null && (
            <p className="mt-2 font-mono text-[11px] text-secondary" data-testid="value-protected">
              Paro real {downtimeH.toFixed(2)} h
              {avoidedH != null ? ` · paro evitado ≈ ${avoidedH.toFixed(2)} h` : ""}
              {inc.value_protected_usd != null ? ` · USD ${Math.round(inc.value_protected_usd).toLocaleString("es-PE")}` : ""}
            </p>
          )}
        </Panel>
      )}
      {showNotes && (
        <Panel icon="edit_note" title="Notas de resolución" subtitle="Registradas al resolver el incidente">
          <blockquote className="whitespace-pre-line border-l-2 border-primary/40 pl-3 text-sm leading-relaxed text-on-surface" data-testid="resolution-notes">
            {notes || "Sin notas registradas."}
          </blockquote>
          <p className="mt-2 flex flex-wrap items-center gap-1.5 font-mono text-[11px] text-outline">
            <Icon name="person" className="text-[14px]" />
            {by?.user_id ? personName(by.user_id) : "—"}
            {role && <span>· {role}</span>}
            {inc.resolved_at && <span>· {fmtDateTime(inc.resolved_at)}</span>}
          </p>
          {inc.components_replaced.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {inc.components_replaced.map((c) => (
                <span key={c} className="chip bg-surface-container-high text-on-surface-variant">{c} · {COMPONENT_BY_ID.get(c)?.name}</span>
              ))}
            </div>
          )}
        </Panel>
      )}
    </>
  );
}

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { errorMessage } from "@/api/errors";
import type { IncidentStatus, MachineStatus, Severity } from "@/api/types";
import { INCIDENT_STATUS_LABEL, SEVERITY_LABEL, STATUS_LABEL } from "@/lib/format";

export const cx = (...xs: (string | false | null | undefined)[]) => xs.filter(Boolean).join(" ");

export function Icon({ name, className, fill }: { name: string; className?: string; fill?: boolean }) {
  return (
    <span aria-hidden="true" className={cx("icon", fill && "icon-fill", className ?? "text-[20px]")}>
      {name}
    </span>
  );
}

// ------------------------------------------------------------------ severidad y estado
const SEV_STYLE: Record<Severity, { chip: string; dot: string; text: string; border: string; icon: string }> = {
  critical: { chip: "bg-danger text-white", dot: "bg-error", text: "text-error", border: "border-l-error", icon: "error" },
  high: { chip: "bg-error/[0.12] text-error", dot: "bg-error/80", text: "text-error", border: "border-l-error/70", icon: "warning" },
  medium: { chip: "bg-tertiary/[0.12] text-tertiary", dot: "bg-tertiary", text: "text-tertiary", border: "border-l-tertiary", icon: "report" },
  low: { chip: "bg-primary/[0.12] text-primary", dot: "bg-primary", text: "text-primary", border: "border-l-primary", icon: "info" },
  info: { chip: "bg-secondary/10 text-secondary", dot: "bg-secondary", text: "text-secondary", border: "border-l-secondary", icon: "check_circle" },
};

export const sevStyle = (s: Severity) => SEV_STYLE[s];

/** Severidad: siempre ícono + texto (nunca solo color). */
export function SeverityBadge({ severity, className }: { severity: Severity; className?: string }) {
  const s = SEV_STYLE[severity];
  return (
    <span className={cx("chip", s.chip, className)}>
      <Icon name={s.icon} className="text-[14px]" fill />
      {SEVERITY_LABEL[severity]}
    </span>
  );
}

const STATUS_STYLE: Record<MachineStatus, { dot: string; text: string; pulse?: boolean }> = {
  operational: { dot: "bg-secondary", text: "text-secondary", pulse: true },
  needs_intervention: { dot: "bg-error", text: "text-error", pulse: true },
  stopped: { dot: "bg-tertiary", text: "text-tertiary" },
  maintenance: { dot: "bg-primary", text: "text-primary" },
  silent: { dot: "bg-idle", text: "text-outline" },
};

export function StatusDot({ status, label = true }: { status: MachineStatus; label?: boolean }) {
  const s = STATUS_STYLE[status];
  return (
    <span className={cx("inline-flex items-center gap-1.5 text-xs font-medium", s.text)}>
      <span className="relative inline-flex h-2 w-2">
        {s.pulse && status !== "operational" && <span className={cx("absolute inset-0 rounded-full af-ping", s.dot)} />}
        <span className={cx("relative inline-block h-2 w-2 rounded-full", s.dot)} />
      </span>
      {label && STATUS_LABEL[status]}
    </span>
  );
}

const INC_STATUS_STYLE: Record<IncidentStatus, string> = {
  detected: "bg-error/15 text-error",
  assigned: "bg-tertiary/[0.12] text-tertiary",
  in_progress: "bg-primary/15 text-primary",
  resolved: "bg-secondary/15 text-secondary",
  closed: "bg-white/[0.05] text-on-surface-variant",
  abandoned: "bg-error/10 text-error",
};
const INC_STATUS_ICON: Record<IncidentStatus, string> = {
  detected: "notification_important",
  assigned: "assignment_ind",
  in_progress: "build",
  resolved: "task_alt",
  closed: "inventory",
  abandoned: "cancel",
};

export function IncidentStatusBadge({ status }: { status: IncidentStatus }) {
  return (
    <span className={cx("chip", INC_STATUS_STYLE[status])}>
      <Icon name={INC_STATUS_ICON[status]} className="text-[14px]" />
      {INCIDENT_STATUS_LABEL[status]}
    </span>
  );
}

/** Barra de salud 0-100 con color por umbral y valor en texto. */
export function HealthBar({ value, compact }: { value: number; compact?: boolean }) {
  const color = value < 40 ? "bg-error" : value < 70 ? "bg-tertiary" : "bg-secondary";
  const text = value < 40 ? "text-error" : value < 70 ? "text-tertiary" : "text-secondary";
  return (
    <div className="flex items-center gap-2" title={`Health score ${value}/100`}>
      <div className={cx("h-1.5 overflow-hidden rounded-full bg-surface-container-highest", compact ? "w-14" : "w-24")}>
        <div className={cx("h-full rounded-full", color)} style={{ width: `${Math.max(2, value)}%` }} />
      </div>
      <span className={cx("font-mono text-xs font-semibold", text)}>{value}</span>
    </div>
  );
}

// ------------------------------------------------------------------ contenedores
export function Panel({
  title,
  subtitle,
  icon,
  iconTone = "primary",
  actions,
  children,
  className,
  bodyClassName,
  id,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  /** Nombre de Material Symbol o un nodo (p. ej. la mascota Arqui) */
  icon?: string | ReactNode;
  iconTone?: "primary" | "error" | "tertiary" | "secondary";
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  id?: string;
}) {
  const tone = { primary: "text-primary", error: "text-error", tertiary: "text-tertiary", secondary: "text-secondary" }[iconTone];
  return (
    <section id={id} className={cx("panel flex flex-col overflow-hidden", className)}>
      <header className="panel-header">
        <div className="flex min-w-0 items-center gap-2.5">
          {icon && (
            <div className={cx("flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-hairline bg-white/[0.03]", tone)}>
              {typeof icon === "string" ? <Icon name={icon} className="text-[16px]" /> : icon}
            </div>
          )}
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold leading-tight tracking-tight text-on-surface">{title}</h2>
            {subtitle && <div className="mt-0.5 truncate text-xs text-outline">{subtitle}</div>}
          </div>
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </header>
      <div className={cx("flex-1", bodyClassName ?? "p-5")}>{children}</div>
    </section>
  );
}

export function KpiCard({
  label,
  value,
  unit,
  delta,
  tone = "neutral",
  badge,
  description,
  footer,
}: {
  label: string;
  value: ReactNode;
  unit?: ReactNode;
  delta?: ReactNode;
  tone?: "neutral" | "good" | "bad" | "warn" | "info";
  badge?: ReactNode;
  description?: ReactNode;
  footer?: ReactNode;
}) {
  const valueTone = { neutral: "text-on-surface", good: "text-on-surface", bad: "text-error", warn: "text-tertiary", info: "text-on-surface" }[tone];
  const border = { neutral: "border-hairline", good: "border-hairline", bad: "border-error/25", warn: "border-hairline", info: "border-hairline" }[tone];
  const unitTone = { neutral: "text-primary", good: "text-secondary", bad: "text-error", warn: "text-tertiary", info: "text-primary" }[tone];
  const ambient = { neutral: "tone-info", good: "tone-good", bad: "tone-critical", warn: "tone-warn", info: "tone-info" }[tone];
  return (
    <div className={cx("ambient flex flex-col justify-between rounded-xl border bg-surface-container-low p-5 transition-[border-color,background-color,transform] duration-300 spring hover:-translate-y-px hover:border-hairline-strong", ambient, border)}>
      <div className="flex items-start justify-between gap-2">
        <span className="label">{label}</span>
        {badge}
      </div>
      <div className="my-4">
        <div className="flex items-baseline gap-2">
          <span key={String(value)} className={cx("metric-tick text-[32px] font-semibold leading-none tracking-[-0.035em] tabular-nums", valueTone)}>
            {value}
          </span>
          {unit && <span className={cx("text-xs font-medium", unitTone)}>{unit}</span>}
          {delta}
        </div>
        {description && <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">{description}</p>}
      </div>
      {footer && <div className="flex items-center justify-between gap-2 border-t border-hairline pt-3 text-xs text-outline">{footer}</div>}
    </div>
  );
}

export function Badge({ tone = "neutral", children, pulse }: { tone?: "good" | "bad" | "warn" | "info" | "neutral"; children: ReactNode; pulse?: boolean }) {
  const t = {
    good: "bg-secondary/10 text-secondary",
    bad: "bg-error/10 text-error",
    warn: "bg-tertiary-container/30 text-tertiary",
    info: "bg-primary/10 text-primary",
    neutral: "bg-white/[0.05] text-on-surface-variant",
  }[tone];
  const d = { good: "bg-secondary", bad: "bg-error", warn: "bg-tertiary", info: "bg-primary", neutral: "bg-outline" }[tone];
  return (
    <span className={cx("chip whitespace-nowrap", t)}>
      {pulse && <span className={cx("h-1.5 w-1.5 rounded-full animate-pulse", d)} />}
      {children}
    </span>
  );
}

// ------------------------------------------------------------------ botones
type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost" | "success";
  icon?: string;
  busy?: boolean;
  size?: "sm" | "md";
};

export function Button({ variant = "secondary", icon, busy, size = "md", className, children, disabled, ...rest }: BtnProps) {
  // Primario claro sobre oscuro (estilo Vercel/Apple); acentos de color solo para acciones con significado
  const v = {
    primary: "bg-on-surface text-background hover:bg-white shadow-[inset_0_1px_0_rgba(255,255,255,0.4)]",
    secondary: "border border-hairline-strong bg-white/[0.04] text-on-surface hover:border-white/20 hover:bg-white/[0.07]",
    danger: "bg-danger text-white hover:bg-danger-hover shadow-[inset_0_1px_0_rgba(255,255,255,0.18)]",
    success: "bg-secondary-container text-white hover:bg-[#00b37c] shadow-[inset_0_1px_0_rgba(255,255,255,0.18)]",
    ghost: "text-on-surface-variant hover:bg-white/[0.06] hover:text-on-surface",
  }[variant];
  const s = size === "sm" ? "h-7 px-2.5 text-xs" : "h-8 px-3.5 text-[13px]";
  return (
    <button
      type="button"
      {...rest}
      disabled={disabled || busy}
      className={cx(
        "inline-flex select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-lg font-medium transition-[background-color,border-color,color,transform] duration-150 ease-out active:scale-[0.97] disabled:pointer-events-none disabled:opacity-40",
        v,
        s,
        className,
      )}
    >
      {busy ? <Spinner className="h-3.5 w-3.5" /> : icon ? <Icon name={icon} className="text-[16px]" /> : null}
      {children}
    </button>
  );
}

// ------------------------------------------------------------------ estados
export function Spinner({ className }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Cargando"
      className={cx("inline-block animate-spin rounded-full border-2 border-current border-r-transparent", className ?? "h-5 w-5 text-primary")}
    />
  );
}

export function Loading({ label = "Cargando…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-10 text-sm text-on-surface-variant">
      <Spinner />
      {label}
    </div>
  );
}

export function Empty({ icon = "inbox", title, children }: { icon?: string; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      <span className="flex h-10 w-10 items-center justify-center rounded-lg border border-hairline bg-white/[0.03]">
        <Icon name={icon} className="text-[20px] text-outline" />
      </span>
      <p className="mt-1 text-sm font-medium text-on-surface">{title}</p>
      {children && <div className="max-w-md text-xs text-on-surface-variant">{children}</div>}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-error/25 bg-error/[0.06] p-3 text-sm text-on-error-container">
      <Icon name="error" className="mt-0.5 text-[18px] text-error" />
      <div className="flex-1">{errorMessage(error)}</div>
      {onRetry && (
        <Button size="sm" variant="ghost" icon="refresh" onClick={onRetry}>
          Reintentar
        </Button>
      )}
    </div>
  );
}

export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className="rounded-lg border border-hairline bg-white/[0.02] p-2.5 text-center">
      <span className="block text-[11px] text-outline">{label}</span>
      <span className={cx("text-sm font-semibold tabular-nums", tone ?? "text-on-surface")}>{value}</span>
    </div>
  );
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: ReactNode }[];
  label: string;
}) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

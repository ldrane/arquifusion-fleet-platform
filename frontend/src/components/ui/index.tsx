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
  critical: { chip: "bg-error text-on-error", dot: "bg-error", text: "text-error", border: "border-l-error", icon: "error" },
  high: { chip: "bg-error-container text-on-error-container", dot: "bg-error/80", text: "text-error", border: "border-l-error/70", icon: "warning" },
  medium: { chip: "bg-tertiary-container/30 text-tertiary", dot: "bg-tertiary", text: "text-tertiary", border: "border-l-tertiary", icon: "report" },
  low: { chip: "bg-primary/15 text-primary", dot: "bg-primary", text: "text-primary", border: "border-l-primary", icon: "info" },
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
  assigned: "bg-tertiary-container/30 text-tertiary",
  in_progress: "bg-primary/15 text-primary",
  resolved: "bg-secondary/15 text-secondary",
  closed: "bg-surface-container-highest text-on-surface-variant",
};
const INC_STATUS_ICON: Record<IncidentStatus, string> = {
  detected: "notification_important",
  assigned: "assignment_ind",
  in_progress: "build",
  resolved: "task_alt",
  closed: "inventory",
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
  icon?: string;
  iconTone?: "primary" | "error" | "tertiary" | "secondary";
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  id?: string;
}) {
  const tone = { primary: "bg-primary/10 text-primary", error: "bg-error/15 text-error", tertiary: "bg-tertiary/15 text-tertiary", secondary: "bg-secondary/10 text-secondary" }[iconTone];
  return (
    <section id={id} className={cx("panel flex flex-col overflow-hidden", className)}>
      <header className="panel-header">
        <div className="flex min-w-0 items-center gap-2.5">
          {icon && (
            <div className={cx("flex h-8 w-8 shrink-0 items-center justify-center rounded-xl", tone)}>
              <Icon name={icon} className="text-[18px]" />
            </div>
          )}
          <div className="min-w-0">
            <h2 className="truncate font-mono text-sm font-bold leading-tight text-on-surface">{title}</h2>
            {subtitle && <div className="truncate font-mono text-[11px] text-outline">{subtitle}</div>}
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
  const border = { neutral: "hover:border-primary/40", good: "hover:border-secondary/40", bad: "border-error/30 hover:border-error", warn: "hover:border-tertiary/40", info: "hover:border-primary/40" }[tone];
  const unitTone = { neutral: "text-primary", good: "text-secondary", bad: "text-error", warn: "text-tertiary", info: "text-primary" }[tone];
  return (
    <div className={cx("flex flex-col justify-between rounded-2xl border border-outline-variant/30 bg-surface-container-low p-5 shadow-sm transition-all", border)}>
      <div className="flex items-start justify-between gap-2">
        <span className="label">{label}</span>
        {badge}
      </div>
      <div className="my-4">
        <div className="flex items-baseline gap-2">
          <span className={cx("font-mono text-3xl font-bold", valueTone)}>{value}</span>
          {unit && <span className={cx("font-mono text-xs font-semibold", unitTone)}>{unit}</span>}
          {delta}
        </div>
        {description && <p className="mt-1 text-xs text-on-surface-variant">{description}</p>}
      </div>
      {footer && <div className="flex items-center justify-between gap-2 border-t border-outline-variant/20 pt-2 font-mono text-xs text-outline">{footer}</div>}
    </div>
  );
}

export function Badge({ tone = "neutral", children, pulse }: { tone?: "good" | "bad" | "warn" | "info" | "neutral"; children: ReactNode; pulse?: boolean }) {
  const t = {
    good: "bg-secondary/10 text-secondary",
    bad: "bg-error-container text-error",
    warn: "bg-tertiary-container/30 text-tertiary",
    info: "bg-primary/10 text-primary",
    neutral: "bg-surface-container-highest text-on-surface-variant",
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
  const v = {
    primary: "bg-primary text-on-primary hover:bg-primary-fixed shadow-sm",
    secondary: "bg-surface-container-high text-on-surface hover:bg-surface-bright border border-outline-variant/30",
    danger: "bg-error text-on-error hover:bg-on-error-container shadow-[0_0_12px_rgba(255,180,171,0.25)]",
    success: "bg-secondary text-on-secondary hover:bg-secondary-fixed",
    ghost: "text-on-surface-variant hover:bg-surface-container hover:text-on-surface",
  }[variant];
  const s = size === "sm" ? "px-2.5 py-1.5 text-xs" : "px-4 py-2 text-xs";
  return (
    <button
      type="button"
      {...rest}
      disabled={disabled || busy}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-xl font-mono font-semibold transition-all active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-50",
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
      <Icon name={icon} className="text-[32px] text-outline" />
      <p className="font-mono text-sm font-semibold text-on-surface">{title}</p>
      {children && <div className="max-w-md text-xs text-on-surface-variant">{children}</div>}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-xl border border-error/30 bg-error-container/20 p-3 text-sm text-on-error-container">
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
    <div className="rounded-xl bg-surface-container-lowest p-2.5 text-center">
      <span className="block font-mono text-[11px] text-outline">{label}</span>
      <span className={cx("font-mono text-sm font-bold", tone ?? "text-on-surface")}>{value}</span>
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

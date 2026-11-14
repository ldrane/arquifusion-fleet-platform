import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import type { FuelItem, ProductivityItem, TelemetryPoint } from "@/api/types";
import { fmt1, VARIABLE_LABEL } from "@/lib/format";

/**
 * Tokens de gráficos (validados con el validador de la skill dataviz sobre la superficie #171b26):
 * categóricos en orden fijo, todos los pares pasan CVD y visión normal. Los acentos de la UI
 * (#adc6ff, #ffb95f) NO se usan como series: fallan la banda de luminosidad.
 */
export const VIZ = {
  series1: "#3987e5",
  series2: "#d95926",
  series3: "#199e70",
  grid: "#262a35",
  axis: "#8c909f",
  text: "#c2c6d6",
  surface: "#171b26",
  reference: "#8c909f",
};

const axisProps = { stroke: VIZ.grid, tick: { fill: VIZ.axis, fontSize: 11, fontFamily: "JetBrains Mono" }, tickLine: false };

function TipBox({ title, rows }: { title: string; rows: { label: string; value: string; color?: string }[] }) {
  return (
    <div className="rounded-xl border border-outline-variant/50 bg-surface-container-lowest/95 px-3 py-2 text-xs shadow-[0_12px_32px_-8px_rgba(0,0,0,0.7)]">
      <div className="mb-1 font-mono text-[11px] text-outline">{title}</div>
      {rows.map((r) => (
        <div key={r.label} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-on-surface-variant">
            {r.color && <span className="h-2 w-2 rounded-full" style={{ background: r.color }} />}
            {r.label}
          </span>
          <span className="font-mono font-semibold text-on-surface">{r.value}</span>
        </div>
      ))}
    </div>
  );
}

const hhmm = (iso: string) => new Date(iso).toLocaleTimeString("es-PE", { hour: "2-digit", minute: "2-digit" });
const ddhh = (iso: string) => new Date(iso).toLocaleString("es-PE", { day: "2-digit", hour: "2-digit" });

/**
 * Una variable de telemetría: línea del promedio + banda min-max del bucket + referencia nominal.
 * Una sola serie (el título la nombra): sin leyenda.
 */
export function TelemetryChart({
  data,
  variable,
  nominal,
  resolution,
}: {
  data: TelemetryPoint[];
  variable: "temperature_c" | "vibration_mm_s" | "pressure_bar" | "fuel_rate_lph" | "health_score";
  nominal?: number;
  resolution: "1m" | "1h";
}) {
  const meta = variable === "health_score" ? { label: "Health score", unit: "/100" } : VARIABLE_LABEL[variable]!;
  const rows = data.map((p) => {
    if (variable === "health_score") return { t: p.bucket_start, avg: p.health_score, band: [p.health_score, p.health_score] as [number, number] };
    const a = p[variable];
    return { t: p.bucket_start, avg: a.avg, band: [a.min, a.max] as [number, number] };
  });
  const last = rows.at(-1)?.avg;
  return (
    <div className="rounded-xl border border-outline-variant/20 bg-surface-container-lowest/60 p-3">
      <div className="mb-1 flex items-baseline justify-between">
        <span className="font-mono text-xs font-semibold text-on-surface">{meta.label}</span>
        <span className="font-mono text-xs text-on-surface-variant">
          {last != null ? `${fmt1(last)} ${meta.unit}` : "—"}
          {nominal != null && <span className="text-outline"> · nominal {fmt1(nominal)}</span>}
        </span>
      </div>
      <div className="h-36">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 6, right: 6, bottom: 0, left: -18 }}>
            <CartesianGrid stroke={VIZ.grid} strokeDasharray="2 4" vertical={false} />
            <XAxis dataKey="t" {...axisProps} tickFormatter={resolution === "1h" ? ddhh : hhmm} minTickGap={40} />
            <YAxis {...axisProps} width={48} domain={["auto", "auto"]} tickFormatter={(v: number) => fmt1(v)} />
            {nominal != null && <ReferenceLine y={nominal} stroke={VIZ.reference} strokeDasharray="4 4" />}
            <Area dataKey="band" stroke="none" fill={VIZ.series1} fillOpacity={0.18} isAnimationActive={false} />
            <Line dataKey="avg" stroke={VIZ.series1} strokeWidth={2} dot={false} isAnimationActive={false} activeDot={{ r: 4, stroke: VIZ.surface, strokeWidth: 2 }} />
            <Tooltip
              cursor={{ stroke: VIZ.axis, strokeDasharray: "3 3" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const r = payload[0]!.payload as (typeof rows)[number];
                return (
                  <TipBox
                    title={new Date(r.t).toLocaleString("es-PE")}
                    rows={[
                      { label: "Promedio", value: `${fmt1(r.avg)} ${meta.unit}`, color: VIZ.series1 },
                      ...(variable !== "health_score" ? [{ label: "Mín – máx", value: `${fmt1(r.band[0])} – ${fmt1(r.band[1])}` }] : []),
                      ...(nominal != null ? [{ label: "Nominal", value: fmt1(nominal) }] : []),
                    ]}
                  />
                );
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/** Desvío de consumo frente a pares del mismo modelo: divergente (azul = mejor, naranja = peor). */
export function FuelDeviationChart({ data }: { data: FuelItem[] }) {
  const rows = data.map((f) => ({ id: f.machine_id, v: f.vs_peers_pct, f }));
  return (
    <div style={{ height: Math.max(220, rows.length * 22 + 40) }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }} barCategoryGap={4}>
          <CartesianGrid stroke={VIZ.grid} strokeDasharray="2 4" horizontal={false} />
          <XAxis type="number" {...axisProps} tickFormatter={(v: number) => `${v > 0 ? "+" : ""}${v}%`} />
          <YAxis type="category" dataKey="id" {...axisProps} width={64} interval={0} />
          <ReferenceLine x={0} stroke={VIZ.reference} />
          <Bar dataKey="v" radius={4} isAnimationActive={false}>
            {rows.map((r) => (
              <Cell key={r.id} fill={r.v > 0 ? VIZ.series2 : VIZ.series1} />
            ))}
          </Bar>
          <Tooltip
            cursor={{ fill: "rgba(173,198,255,0.06)" }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const f = (payload[0]!.payload as (typeof rows)[number]).f;
              return (
                <TipBox
                  title={`${f.machine_id} · zona ${f.zone}`}
                  rows={[
                    { label: "vs pares", value: `${f.vs_peers_pct > 0 ? "+" : ""}${fmt1(f.vs_peers_pct)}%`, color: f.vs_peers_pct > 0 ? VIZ.series2 : VIZ.series1 },
                    { label: "vs su historial", value: `${f.vs_own_history_pct > 0 ? "+" : ""}${fmt1(f.vs_own_history_pct)}%` },
                    { label: "Consumo", value: `${fmt1(f.lph)} L/h` },
                    { label: "L por tonelada", value: f.l_per_ton.toFixed(3) },
                  ]}
                />
              );
            }}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

const CLASS_COLOR: Record<ProductivityItem["classification"], string> = {
  normal: VIZ.series1,
  overused: VIZ.series2,
  underused: VIZ.series3,
};
export const CLASS_LABEL: Record<ProductivityItem["classification"], string> = {
  normal: "Uso normal",
  overused: "Sobreexplotada",
  underused: "Subutilizada",
};

/** Matriz productividad × costo (RF-08). 3 clases = los 3 primeros slots, válidos en todos los pares. */
export function ProductivityMatrix({ data }: { data: ProductivityItem[] }) {
  const costs = [...data].map((d) => d.cost_per_hour_usd).sort((a, b) => a - b);
  const medCost = costs[Math.floor(costs.length / 2)] ?? 0;
  const groups = (["normal", "overused", "underused"] as const).map((c) => ({ c, rows: data.filter((d) => d.classification === c) }));
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-4 text-xs text-on-surface-variant" role="list" aria-label="Leyenda">
        {groups.map((g) => (
          <span key={g.c} role="listitem" className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: CLASS_COLOR[g.c] }} />
            {CLASS_LABEL[g.c]} ({g.rows.length})
          </span>
        ))}
      </div>
      <div className="h-80">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 10, right: 16, bottom: 18, left: -8 }}>
            <CartesianGrid stroke={VIZ.grid} strokeDasharray="2 4" />
            <XAxis type="number" dataKey="utilization_pct" name="Utilización" unit="%" domain={[0, 100]} {...axisProps} label={{ value: "Utilización %", position: "insideBottom", offset: -10, fill: VIZ.axis, fontSize: 11 }} />
            <YAxis type="number" dataKey="cost_per_hour_usd" name="Costo/h" {...axisProps} width={56} tickFormatter={(v: number) => `$${Math.round(v)}`} />
            <ZAxis range={[64, 64]} />
            <ReferenceLine x={65} stroke={VIZ.reference} strokeDasharray="4 4" />
            <ReferenceLine y={medCost} stroke={VIZ.reference} strokeDasharray="4 4" />
            {groups.map((g) => (
              <Scatter key={g.c} name={CLASS_LABEL[g.c]} data={g.rows} fill={CLASS_COLOR[g.c]} stroke={VIZ.surface} strokeWidth={2} isAnimationActive={false} />
            ))}
            <Tooltip
              cursor={{ strokeDasharray: "3 3", stroke: VIZ.axis }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0]!.payload as ProductivityItem;
                return (
                  <TipBox
                    title={`${d.machine_id} · zona ${d.zone}`}
                    rows={[
                      { label: CLASS_LABEL[d.classification], value: "", color: CLASS_COLOR[d.classification] },
                      { label: "Utilización", value: `${fmt1(d.utilization_pct)}%` },
                      { label: "Costo/hora", value: `$${fmt1(d.cost_per_hour_usd)}` },
                    ]}
                  />
                );
              }}
            />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-[11px] text-outline">Líneas punteadas: 65% de utilización y costo/hora mediano (límites de cuadrante).</p>
    </div>
  );
}

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { errorMessage } from "@/api/errors";
import type { SimState } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { can } from "@/auth/permissions";
import { DEMO_MACHINE, SIMULATOR_SCENARIOS, ZONES } from "@/demo/data";
import { api, world } from "@/services";
import { useViewState } from "@/state/viewState";
import { Button, Icon } from "../ui";
import { Modal } from "../ui/Modal";
import { useToast } from "../ui/Toast";

/**
 * Control del simulador (TAREA-08).
 * - Modo http: escribe el estado en SSM (`/sim/scenario` y `/sim/stop`); la Lambda `sim-driver` inyecta en AWS real.
 * - Modo demo: inyecta el escenario en el mundo local (`DemoApi.simStart`).
 * Refresca `/sim/state` cada 10 s mientras el modal está abierto y muestra la cuenta regresiva.
 */
export function SimulatorControl() {
  const [open, setOpen] = useState(false);
  const [scenario, setScenario] = useViewState("sim.scenario", "degradacion");
  const [machine, setMachine] = useViewState("sim.machine", "");
  const [zone, setZone] = useViewState("sim.zone", "");
  const [autopilot, setAutopilot] = useState(world?.autopilot ?? true);
  const [state, setState] = useState<SimState | null>(null);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  const { role } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const isDemo = !!world;

  const allowed = isDemo || can(role, "simulate");

  useEffect(() => {
    if (!open) return;
    let alive = true;
    const load = () =>
      api
        .simState()
        .then((s) => alive && setState(s))
        .catch(() => undefined);
    void load();
    const timer = setInterval(load, 10_000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [open]);

  useEffect(() => {
    if (!open || !state?.enabled) return;
    const timer = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [open, state?.enabled]);

  if (!allowed) return null;

  const remainingMin = state?.expires_at
    ? Math.max(0, Math.ceil((new Date(state.expires_at).getTime() - Date.now()) / 60_000))
    : null;
  void tick; // fuerza el recálculo de la cuenta regresiva cada segundo

  const start = async () => {
    setBusy(true);
    try {
      const next = await api.simStart({
        scenario,
        machines: machine.trim() ? [machine.trim().toUpperCase()] : undefined,
        zone: zone || null,
        duration_min: 20,
        speedup: 240,
        interval_s: 10,
      });
      setState(next);
      toast(`Escenario ${scenario} encendido en ${isDemo ? "demo" : "AWS real"}`, "good");
      if (isDemo) {
        setOpen(false);
        navigate("/incidentes");
      }
    } catch (e) {
      toast(errorMessage(e), "bad");
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    setBusy(true);
    try {
      setState(await api.simStop());
      toast("Simulador apagado", "good");
    } catch (e) {
      toast(errorMessage(e), "bad");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="hidden h-8 items-center gap-1.5 rounded-lg border border-hairline-strong px-2.5 text-[13px] font-medium text-on-surface-variant transition-colors duration-150 hover:bg-white/[0.05] hover:text-on-surface active:scale-[0.97] md:flex"
        title={isDemo ? "Simulador de flota (demo)" : "Simulador de flota (AWS real)"}
      >
        <Icon name="science" className="text-[16px] text-tertiary" />
        Simulador
      </button>
      <Modal
        title="Simulador de flota"
        open={open}
        onClose={() => setOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancelar
            </Button>
            {state?.enabled ? (
              <Button variant="ghost" icon="stop_circle" onClick={stop} disabled={busy}>
                Detener
              </Button>
            ) : null}
            <Button variant="danger" icon="bolt" onClick={start} disabled={busy}>
              Inyectar escenario
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-5 text-sm">
          <div className="flex flex-col gap-2">
            <span className="inline-flex w-fit items-center gap-1.5 rounded-md bg-tertiary/[0.12] px-1.5 py-0.5 text-[11px] font-medium text-tertiary">
              <Icon name="science" className="text-[13px]" />
              {isDemo ? "Modo demo" : "AWS real · sim-driver serverless"}
            </span>
            <p className="text-[13px] leading-relaxed text-on-surface-variant">
              {isDemo
                ? "Inyecta una anomalía en el mundo local, igual que el botón de un operador en la consola."
                : "Enciende el gemelo de flota serverless: la Lambda sim-driver envía telemetría a POST /telemetry y GestionIncidente reacciona en vivo."}
            </p>
            {state?.enabled ? (
              <div className="flex flex-wrap items-center gap-2 rounded-lg border border-hairline bg-white/[0.02] p-3 text-[12px]">
                <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 font-medium text-emerald-400">
                  {isDemo ? "DEMO activo" : "AWS real"}
                </span>
                <span className="font-mono">{state.scenario}</span>
                {remainingMin !== null ? <span>· {remainingMin} min restantes</span> : null}
                {state.machines?.length ? <span>· {state.machines.join(", ")}</span> : null}
              </div>
            ) : null}
          </div>
          <label className="flex flex-col gap-1">
            <span className="label">Escenario</span>
            <select className="input" value={scenario} onChange={(e) => setScenario(e.target.value)}>
              {SIMULATOR_SCENARIOS.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label} ({s.severity})
                </option>
              ))}
              <option value="grupal_zona">Incidente grupal por zona: combustible contaminado (RF-12)</option>
            </select>
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1">
              <span className="label">Máquina (opcional)</span>
              <input className="input font-mono" placeholder={DEMO_MACHINE} value={machine} onChange={(e) => setMachine(e.target.value)} disabled={scenario === "grupal_zona"} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="label">Zona (opcional)</span>
              <select className="input" value={zone} onChange={(e) => setZone(e.target.value)}>
                <option value="">Cualquiera</option>
                {ZONES.map((z) => (
                  <option key={z} value={z}>
                    {z}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {isDemo ? (
            <label className="flex cursor-pointer items-center justify-between gap-4 rounded-lg border border-hairline bg-white/[0.02] p-3.5 transition-colors duration-150 hover:bg-white/[0.04]">
              <span>
                <span className="block text-[13px] font-medium text-on-surface">Piloto automático</span>
                <span className="mt-0.5 block text-xs leading-relaxed text-on-surface-variant">
                  Los técnicos simulados aceptan y resuelven solos y aparecen anomalías nuevas. TEC-07 (usuario u-tec-07) siempre espera tu acción.
                </span>
              </span>
              <input
                type="checkbox"
                role="switch"
                className="peer sr-only"
                checked={autopilot}
                onChange={(e) => {
                  if (world) world.autopilot = e.target.checked;
                  setAutopilot(e.target.checked);
                }}
              />
              <span
                aria-hidden="true"
                className="relative h-[22px] w-[38px] shrink-0 rounded-full bg-white/[0.12] transition-colors duration-200 ease-apple peer-checked:bg-secondary-container peer-focus-visible:ring-2 peer-focus-visible:ring-primary/60 after:absolute after:left-[2px] after:top-[2px] after:h-[18px] after:w-[18px] after:rounded-full after:bg-white after:shadow-[0_1px_3px_rgba(0,0,0,0.4)] after:transition-transform after:duration-200 after:ease-apple peer-checked:after:translate-x-4"
              />
            </label>
          ) : null}
        </div>
      </Modal>
    </>
  );
}

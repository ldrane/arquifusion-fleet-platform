import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { errorMessage } from "@/api/errors";
import { DEMO_MACHINE, SIMULATOR_SCENARIOS, ZONES } from "@/demo/data";
import { world } from "@/services";
import { useViewState } from "@/state/viewState";
import { Button, Icon } from "../ui";
import { Modal } from "../ui/Modal";
import { useToast } from "../ui/Toast";

/**
 * Solo modo demo: equivale a correr `python -m simulator stream --scenario ...` (A) contra la API.
 * Sirve para el pitch: inyectar el escenario justo cuando se está mostrando la pantalla.
 */
export function SimulatorControl() {
  const [open, setOpen] = useState(false);
  const [scenario, setScenario] = useViewState("sim.scenario", "degradacion");
  const [machine, setMachine] = useViewState("sim.machine", "");
  const [zone, setZone] = useViewState("sim.zone", "");
  const [autopilot, setAutopilot] = useState(world?.autopilot ?? true);
  const toast = useToast();
  const navigate = useNavigate();
  const sim = world;
  if (!sim) return null;

  const inject = () => {
    try {
      const inc = sim.inject(scenario, machine.trim().toUpperCase() || undefined, zone || undefined);
      toast(`Escenario inyectado: ${inc.incident_id} en ${inc.machine_ids.join(", ")}`, "good");
      setOpen(false);
      navigate(`/incidentes/${inc.incident_id}`);
    } catch (e) {
      toast(errorMessage(e), "bad");
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="hidden h-8 items-center gap-1.5 rounded-lg border border-hairline-strong px-2.5 text-[13px] font-medium text-on-surface-variant transition-colors duration-150 hover:bg-white/[0.05] hover:text-on-surface active:scale-[0.97] md:flex"
        title="Simulador de flota (solo modo demo)"
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
            <Button variant="danger" icon="bolt" onClick={inject}>
              Inyectar escenario
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-5 text-sm">
          <div className="flex flex-col gap-2">
            <span className="inline-flex w-fit items-center gap-1.5 rounded-md bg-tertiary/[0.12] px-1.5 py-0.5 text-[11px] font-medium text-tertiary">
              <Icon name="science" className="text-[13px]" />
              Solo modo demo
            </span>
            <p className="text-[13px] leading-relaxed text-on-surface-variant">
              Inyecta una anomalía como lo haría <code className="rounded bg-white/[0.06] px-1 py-px font-mono text-[12px] text-on-surface">python -m simulator stream</code>. La detecta{" "}
              <span className="font-mono text-[12px] text-on-surface">procesar</span> y arranca <span className="font-mono text-[12px] text-on-surface">GestionIncidente</span>: diagnóstico IA, asignación y notificación.
            </p>
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
                sim.autopilot = e.target.checked;
                setAutopilot(e.target.checked);
              }}
            />
            {/* Interruptor estilo iOS */}
            <span
              aria-hidden="true"
              className="relative h-[22px] w-[38px] shrink-0 rounded-full bg-white/[0.12] transition-colors duration-200 ease-apple peer-checked:bg-secondary-container peer-focus-visible:ring-2 peer-focus-visible:ring-primary/60 after:absolute after:left-[2px] after:top-[2px] after:h-[18px] after:w-[18px] after:rounded-full after:bg-white after:shadow-[0_1px_3px_rgba(0,0,0,0.4)] after:transition-transform after:duration-200 after:ease-apple peer-checked:after:translate-x-4"
            />
          </label>
        </div>
      </Modal>
    </>
  );
}

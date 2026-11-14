import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { errorMessage } from "@/api/errors";
import { SCENARIOS, ZONES } from "@/demo/data";
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
        className="hidden items-center gap-1.5 rounded-full border border-tertiary/30 bg-tertiary/10 px-3 py-1 font-mono text-xs font-semibold text-tertiary hover:bg-tertiary/20 md:flex"
        title="Simulador de flota (solo modo demo)"
      >
        <Icon name="science" className="text-[16px]" />
        Simulador
      </button>
      <Modal
        title="Simulador de flota · modo demo"
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
        <div className="flex flex-col gap-4 text-sm">
          <p className="text-xs text-on-surface-variant">
            Equivale a <code className="font-mono text-primary">python -m simulator stream --scenario …</code>: genera la anomalía, la detecta
            <span className="font-mono"> procesar</span> y arranca <span className="font-mono">GestionIncidente</span> (diagnóstico IA, scoring, notificación).
          </p>
          <label className="flex flex-col gap-1">
            <span className="label">Escenario</span>
            <select className="input" value={scenario} onChange={(e) => setScenario(e.target.value)}>
              {SCENARIOS.map((s) => (
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
              <input className="input font-mono" placeholder="EX-023" value={machine} onChange={(e) => setMachine(e.target.value)} disabled={scenario === "grupal_zona"} />
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
          <label className="flex items-center justify-between gap-3 rounded-xl border border-outline-variant/30 bg-surface-container-lowest p-3">
            <span>
              <span className="block text-sm font-semibold text-on-surface">Piloto automático</span>
              <span className="text-xs text-on-surface-variant">
                Los técnicos simulados aceptan y resuelven solos y aparecen anomalías nuevas. TEC-07 (usuario u-tec-07) siempre espera tu acción.
              </span>
            </span>
            <input
              type="checkbox"
              className="h-5 w-5 accent-[#adc6ff]"
              checked={autopilot}
              onChange={(e) => {
                sim.autopilot = e.target.checked;
                setAutopilot(e.target.checked);
              }}
            />
          </label>
        </div>
      </Modal>
    </>
  );
}

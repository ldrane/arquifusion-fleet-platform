import { type FormEvent, useState } from "react";
import { useAuth } from "@/auth/AuthContext";
import { Logo } from "@/components/brand/Logo";
import { Button, cx, Icon } from "@/components/ui";
import { hasCognito, isDemo } from "@/config";
import { DEMO_USERS } from "@/demo/data";
import { ROLE_LABEL, ZONE_LABEL } from "@/lib/format";

const ROLE_ICON: Record<string, string> = {
  operador: "visibility",
  tecnico: "engineering",
  mantenimiento: "build",
  supervisor: "supervisor_account",
  admin: "admin_panel_settings",
  gerencia: "monitoring",
};

const ROLE_PITCH: Record<string, string> = {
  operador: "Mapa y cola de su zona, sin comandos",
  tecnico: "Acepta, resuelve y chatea sus incidentes (golden path)",
  mantenimiento: "Despacho, reasignación, inventario y plan preventivo",
  supervisor: "Supervisión de zona, KPIs y combustible",
  admin: "Todo, incluido reentrenar el modelo",
  gerencia: "KPIs, resumen IA y eficiencia (solo lectura)",
};

function DemoLogin() {
  const { loginDemo } = useAuth();
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-on-surface-variant">
        Modo demo: sin AWS ni GCP. Elige un usuario (los mismos del runbook H0) para ver la consola con su rol y su zona.
      </p>
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {DEMO_USERS.map((u) => (
          <li key={u.user_id}>
            <button
              type="button"
              onClick={() => loginDemo(u.user_id)}
              className="flex w-full items-start gap-3 rounded-xl border border-hairline bg-surface-container-lowest p-3 text-left transition-all hover:border-primary hover:bg-primary/5"
            >
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <Icon name={ROLE_ICON[u.role] ?? "person"} />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-on-surface">{u.name}</span>
                <span className="block font-mono text-[11px] text-primary">
                  {ROLE_LABEL[u.role]} · {ZONE_LABEL(u.zone)}
                </span>
                <span className="block text-[11px] text-on-surface-variant">{ROLE_PITCH[u.role]}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CognitoLogin() {
  const { login, completeChallenge } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [challenge, setChallenge] = useState<{ session: string; username: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (challenge) await completeChallenge(challenge.username, challenge.session, newPassword);
      else {
        const r = await login(username, password);
        if (r.challenge) setChallenge(r.challenge);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (!hasCognito) {
    return (
      <p role="alert" className="rounded-xl border border-tertiary/30 bg-tertiary/10 p-3 text-sm text-tertiary">
        Falta <code className="font-mono">VITE_COGNITO_CLIENT_ID</code>. Configúralo en <code className="font-mono">frontend/.env.local</code> o quita <code className="font-mono">VITE_API_URL</code> para usar el modo demo.
      </p>
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      {!challenge ? (
        <>
          <label className="flex flex-col gap-1">
            <span className="label">Usuario</span>
            <input className="input font-mono" autoComplete="username" required value={username} onChange={(e) => setUsername(e.target.value)} placeholder="u-tec-07" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="label">Contraseña</span>
            <input className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
        </>
      ) : (
        <label className="flex flex-col gap-1">
          <span className="label">Nueva contraseña (primer ingreso)</span>
          <input className="input" type="password" autoComplete="new-password" required minLength={8} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
        </label>
      )}
      {error && <p role="alert" className="text-sm text-error">{error}</p>}
      <Button type="submit" variant="primary" icon="login" busy={busy}>
        {challenge ? "Guardar y entrar" : "Ingresar"}
      </Button>
      <p className="text-[11px] text-outline">Autenticación con Amazon Cognito (ID token). El rol y la zona salen de GET /me.</p>
    </form>
  );
}

export function Login() {
  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background p-4">
      {/* Retícula de plano muy tenue, desvanecida hacia los bordes */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-[0.35] [background-image:linear-gradient(rgba(255,255,255,0.05)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.05)_1px,transparent_1px)] [background-size:48px_48px] [mask-image:radial-gradient(ellipse_at_center,black_20%,transparent_70%)]"
      />
      <div className={cx("relative w-full rounded-2xl bg-surface-container-low/90 p-7 shadow-modal backdrop-blur-xl animate-dialog-in", isDemo ? "max-w-2xl" : "max-w-md")}>
        <div className="mb-6 flex items-center gap-3">
          <Logo className="h-9 w-9" />
          <div>
            <div className="text-[17px] font-semibold tracking-[-0.02em] text-on-surface">ArquiFusion</div>
            <div className="text-xs text-outline">Centro táctico de mina · OP-01</div>
          </div>
          {isDemo && <span className="chip ml-auto bg-tertiary/[0.12] text-tertiary">Modo demo</span>}
        </div>
        {isDemo ? <DemoLogin /> : <CognitoLogin />}
      </div>
    </div>
  );
}

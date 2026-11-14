import { type FormEvent, useState } from "react";
import { useAuth } from "@/auth/AuthContext";
import { Logo } from "@/components/layout/Header";
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
              className="flex w-full items-start gap-3 rounded-xl border border-outline-variant/40 bg-surface-container-lowest p-3 text-left transition-all hover:border-primary hover:bg-primary/5"
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
      <p className="text-[11px] text-outline">Autenticación con Amazon Cognito (ID token). El rol y la zona salen de GET /v1/me.</p>
    </form>
  );
}

export function Login() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className={cx("w-full rounded-2xl border border-outline-variant/40 bg-surface-container-low p-6 shadow-[0_12px_32px_-8px_rgba(0,0,0,0.7)]", isDemo ? "max-w-2xl" : "max-w-md")}>
        <div className="mb-5 flex items-center gap-3">
          <Logo />
          <div>
            <div className="font-mono text-sm font-bold uppercase tracking-wider text-on-surface">ArquiFusion</div>
            <div className="font-mono text-[11px] uppercase tracking-wider text-outline">Centro Táctico de Mina · OP-01</div>
          </div>
          {isDemo && <span className="ml-auto chip bg-tertiary/15 text-tertiary">Modo demo</span>}
        </div>
        {isDemo ? <DemoLogin /> : <CognitoLogin />}
      </div>
    </div>
  );
}

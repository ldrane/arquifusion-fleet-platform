/**
 * Login contra Cognito con USER_PASSWORD_AUTH (runbook H0 §5: el app client lo permite).
 * Llamada directa a la API pública de Cognito por HTTPS: sin SDK, sin secretos en el front.
 * Se usa el ID token (trae email y custom:zone; el access token no).
 */
import { config } from "@/config";

export interface CognitoTokens {
  idToken: string;
  refreshToken: string | null;
  expiresAt: number; // epoch ms
}

export type LoginResult =
  | { kind: "ok"; tokens: CognitoTokens }
  | { kind: "new_password"; session: string; username: string };

const endpoint = () => `https://cognito-idp.${config.cognito.region}.amazonaws.com/`;

async function call(target: string, body: unknown): Promise<any> {
  let res: Response;
  try {
    res = await fetch(endpoint(), {
      method: "POST",
      headers: {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": `AWSCognitoIdentityProviderService.${target}`,
      },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error(`No se pudo contactar a Cognito (${config.cognito.region}). Revisa tu conexión.`);
  }
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    const type = String(json.__type ?? "Error").split("#").pop();
    const msg: Record<string, string> = {
      NotAuthorizedException: "Usuario o contraseña incorrectos.",
      UserNotFoundException: "Usuario o contraseña incorrectos.",
      PasswordResetRequiredException: "Debes restablecer tu contraseña.",
      InvalidPasswordException: "La contraseña no cumple la política del User Pool.",
      TooManyRequestsException: "Demasiados intentos; espera un momento.",
    };
    throw new Error(msg[type ?? ""] ?? json.message ?? `Cognito respondió ${res.status}`);
  }
  return json;
}

function toTokens(r: any, previousRefresh: string | null = null): CognitoTokens {
  const a = r.AuthenticationResult;
  return {
    idToken: a.IdToken,
    refreshToken: a.RefreshToken ?? previousRefresh,
    expiresAt: Date.now() + (a.ExpiresIn ?? 3600) * 1000,
  };
}

export async function login(username: string, password: string): Promise<LoginResult> {
  const r = await call("InitiateAuth", {
    AuthFlow: "USER_PASSWORD_AUTH",
    ClientId: config.cognito.clientId,
    AuthParameters: { USERNAME: username, PASSWORD: password },
  });
  if (r.ChallengeName === "NEW_PASSWORD_REQUIRED") {
    return { kind: "new_password", session: r.Session, username };
  }
  if (!r.AuthenticationResult) throw new Error(`Desafío no soportado: ${r.ChallengeName}`);
  return { kind: "ok", tokens: toTokens(r) };
}

/** Usuarios demo creados por admin: primer login exige contraseña nueva. */
export async function completeNewPassword(username: string, session: string, newPassword: string) {
  const r = await call("RespondToAuthChallenge", {
    ChallengeName: "NEW_PASSWORD_REQUIRED",
    ClientId: config.cognito.clientId,
    Session: session,
    ChallengeResponses: { USERNAME: username, NEW_PASSWORD: newPassword },
  });
  return toTokens(r);
}

export async function refresh(refreshToken: string): Promise<CognitoTokens> {
  const r = await call("InitiateAuth", {
    AuthFlow: "REFRESH_TOKEN_AUTH",
    ClientId: config.cognito.clientId,
    AuthParameters: { REFRESH_TOKEN: refreshToken },
  });
  return toTokens(r, refreshToken);
}

/** Lee los claims de un JWT sin validarlo (la validación la hace el authorizer de API Gateway). */
export function decodeJwt<T = Record<string, unknown>>(token: string): T {
  const part = token.split(".")[1] ?? "";
  const b64 = part.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(part.length / 4) * 4, "=");
  const json = decodeURIComponent(
    atob(b64)
      .split("")
      .map((c) => `%${c.charCodeAt(0).toString(16).padStart(2, "0")}`)
      .join(""),
  );
  return JSON.parse(json) as T;
}

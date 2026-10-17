import type { AppMode, UserIdentity } from "./types";

/** Browser-only demo-session helpers. Live sessions are created only by Google OAuth. */
const SESSION_COOKIES = ["__session", "cargoclear_session_token"] as const;
const DEMO_PREFIX = "mock-jwt-";
const DEMO_ROLE: UserIdentity["role"] = "LICENSED_CHA";
const DAY_SECONDS = 24 * 60 * 60;

export const DEMO_ACCOUNTS = [
  { email: "demo-cha@customs.com", label: "customs.com" },
  { email: "agent@dhl.com", label: "dhl.com" },
  { email: "broker@fedex.com", label: "fedex.com" },
] as const;

export function demoToken(email: string): string {
  return `${DEMO_PREFIX}${email.trim().toLowerCase()}-${DEMO_ROLE}`;
}

export function demoUserFromCookie(cookie: string): UserIdentity | null {
  const match = cookie.match(/(?:__session|cargoclear_session_token)=mock-jwt-([^;]+)/);
  if (!match?.[1]) return null;
  const payload = decodeURIComponent(match[1]);
  const parts = payload.split("-");
  const role = (parts.length > 1 ? parts.at(-1) : DEMO_ROLE) as UserIdentity["role"];
  const email = parts.length > 1 ? parts.slice(0, -1).join("-") : payload;
  if (!email) return null;
  const tenant_id = email.includes("@") ? email.split("@").at(-1)! : "customs.com";
  return { user_id: `usr-${email}`, email, name: email.split("@")[0].toUpperCase(), tenant_id, role, issuer: "https://accounts.google.com" };
}

export function storeDemoSessionToken(token: string): void {
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  for (const name of SESSION_COOKIES) document.cookie = `${name}=${token}; path=/; max-age=${DAY_SECONDS}; SameSite=Lax${secure}`;
}

/** Refuse to mint a mock session unless the backend explicitly reports demo mode. */
export function demoSignIn(email: string, appMode: AppMode | undefined): boolean {
  if (appMode !== "demo" || typeof window === "undefined") return false;
  storeDemoSessionToken(demoToken(email));
  return true;
}

export function clearSessionCookies(): void {
  const secure = typeof window !== "undefined" && window.location.protocol === "https:" ? "; Secure" : "";
  for (const name of [...SESSION_COOKIES, "cargoclear_google_id_token"]) {
    document.cookie = `${name}=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT${secure}`;
  }
}

export function signOut(): void {
  clearSessionCookies();
  window.location.href = "/api/auth/logout?returnTo=/";
}

/**
 * Server-side proxy helpers (no Next.js imports, so they are unit-testable: tests/proxy.unit.spec.ts).
 *
 * The browser only ever talks to /api/proxy/...; the Next.js server forwards to the API at the runtime-only
 * API_BASE. When the API is a PRIVATE Cloud Run service (API_AUTH_MODE=google-id-token) every upstream request
 * carries a Google-signed ID token for the API's URL; the token comes from the metadata server of the identity this
 * UI service runs as, and that identity alone holds roles/run.invoker on the API.
 *
 * Environment (all server-side, read at request time):
 *   API_BASE          where the API is (default http://localhost:8080)
 *   API_AUTH_MODE     "google-id-token" to authenticate upstream calls; anything else/unset = no Authorization header
 *   TRUSTED_PROXY_HOPS how many Google-controlled hops append to X-Forwarded-For before this server (default 1:
 *                     Cloud Run's own front end; use 2 behind an external HTTPS load balancer)
 *   GCE_METADATA_HOST override of the metadata server host (tests only)
 */

import { isIP } from "node:net";

/** The header the API reads the end user's IP from (backend: CLIENT_IP_HEADER). Always overwritten here. */
export const CLIENT_IP_HEADER = "x-cargoclear-client-ip";

/** Request headers that are forwarded to the API. Everything else (cookies, authorization, ...) is dropped. */
const FORWARDED_REQUEST_HEADERS = [
  "content-type",
  "content-length",
  "accept",
  "last-event-id",
  "if-none-match",
  "range",
  "x-cargoclear-user-token",
] as const;

/** Response headers that must not be copied: the body is re-streamed (and may have been decoded) by fetch. */
const DROPPED_RESPONSE_HEADERS = [
  "content-encoding",
  "content-length",
  "transfer-encoding",
  "connection",
  "keep-alive",
  "set-cookie",
] as const;

const REQUEST_ID_PATTERN = /^[A-Za-z0-9._-]{1,64}$/;

export function backendBase(env: NodeJS.ProcessEnv = process.env): string {
  if (env.API_BASE) {
    return env.API_BASE;
  }
  if (env.NODE_ENV === "production" && env.ALLOW_LOCALHOST !== "true") {
    throw new Error(
      "API_BASE environment variable is missing in production. " +
      "Configure API_BASE to point to the backend service (e.g. Cloud Run API URL) " +
      "or set ALLOW_LOCALHOST=true for local override."
    );
  }
  return "http://localhost:8080";
}

export function authMode(env: NodeJS.ProcessEnv = process.env): "google-id-token" | "none" {
  return env.API_AUTH_MODE === "google-id-token" ? "google-id-token" : "none";
}

/**
 * The upstream URL for /api/proxy/<segments>, or null when the path is not acceptable.
 *
 * A segment may not be empty, "." or "..", nor carry a slash, backslash, NUL or percent-encoded form of those: without
 * this `/api/proxy/..%2F..%2Fhealthz` would climb out of /api/v1. The result must still be below /api/v1/.
 */
export function buildTargetUrl(base: string, segments: string[], search = ""): URL | null {
  if (segments.length === 0) return null;
  for (const segment of segments) {
    let decoded: string;
    try {
      decoded = decodeURIComponent(segment);
    } catch {
      return null;
    }
    if (decoded === "" || decoded === "." || decoded === "..") return null;
    if (/[\\/\0]/.test(decoded)) return null;
  }
  const url = new URL(`/api/v1/${segments.map((s) => encodeURIComponent(decodeURIComponent(s))).join("/")}`, base);
  if (!url.pathname.startsWith("/api/v1/")) return null;
  url.search = search;
  return url;
}

/**
 * Whether the proxy forwards this method for this path. GET and POST go everywhere; DELETE goes to one place only, removing one
 * document of a bundle (`bundles/<id>/documents/<document>`): the API has no other DELETE route, and the proxy does not open a
 * method wider than the one thing a person can do with it. Segments are compared as the browser meant them (percent-decoded).
 */
export function isForwardable(method: string, segments: string[]): boolean {
  if (method === "GET" || method === "POST") return true;
  if (method !== "DELETE" || segments.length !== 4) return false;
  try {
    const decoded = segments.map((segment) => decodeURIComponent(segment));
    return decoded[0] === "bundles" && decoded[2] === "documents" && decoded[1] !== "" && decoded[3] !== "";
  } catch {
    return false;
  }
}

/** True for the SSE endpoint: it lives as long as the browser keeps it open and must not get a request deadline. */
export function isStreamPath(segments: string[]): boolean {
  return segments.length > 0 && segments[segments.length - 1] === "stream";
}

/** The end user's IP: the entry `hops` from the END of X-Forwarded-For (the entries before it are client-supplied). */
export function clientIpFrom(headers: Headers, hops = 1): string | null {
  const entries = (headers.get("x-forwarded-for") ?? "")
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
  const candidate = entries[entries.length - Math.max(1, hops)];
  return candidate !== undefined && isIP(candidate) !== 0 ? candidate : null;
}

export function trustedProxyHops(env: NodeJS.ProcessEnv = process.env): number {
  const hops = Number.parseInt(env.TRUSTED_PROXY_HOPS ?? "1", 10);
  return Number.isInteger(hops) && hops >= 1 ? hops : 1;
}

export interface UpstreamHeaderOptions {
  idToken: string | null;
  clientIp: string | null;
  requestId: string;
}

/** The headers sent to the API: the allowlisted ones from the browser, plus what this server adds itself. */
export function upstreamRequestHeaders(incoming: Headers, options: UpstreamHeaderOptions): Headers {
  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = incoming.get(name);
    if (value !== null) headers.set(name, value);
  }
  headers.set("x-request-id", options.requestId);
  // never copied from the browser: set here from what this server itself observed
  if (options.clientIp) headers.set(CLIENT_IP_HEADER, options.clientIp);
  if (options.idToken) headers.set("authorization", `Bearer ${options.idToken}`);
  return headers;
}

/** The request id to use: the browser's if it is well formed, else a new one. */
export function requestIdFor(incoming: Headers, generate: () => string = () => crypto.randomUUID()): string {
  const supplied = incoming.get("x-request-id");
  return supplied !== null && REQUEST_ID_PATTERN.test(supplied) ? supplied : generate();
}

export function downstreamResponseHeaders(upstream: Headers): Headers {
  const headers = new Headers(upstream);
  for (const name of DROPPED_RESPONSE_HEADERS) headers.delete(name);
  return headers;
}

/** The fixed error body of the proxy itself (the API's own errors pass through untouched). */
export function proxyError(code: string, message: string, requestId: string) {
  return { code, message, detail: null, request_id: requestId };
}

// ---------------------------------------------------------------------------
// Google ID token for the private API
// ---------------------------------------------------------------------------

export class UpstreamAuthError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "UpstreamAuthError";
  }
}

interface CachedToken {
  token: string;
  /** epoch ms at which the token must be replaced (5 minutes before it expires) */
  refreshAt: number;
}

const REFRESH_MARGIN_MS = 5 * 60 * 1000;
const FALLBACK_TTL_MS = 30 * 60 * 1000;
const METADATA_TIMEOUT_MS = 3000;

function expiryMs(token: string): number | null {
  const payload = token.split(".")[1];
  if (!payload) return null;
  try {
    const claims = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as { exp?: unknown };
    return typeof claims.exp === "number" ? claims.exp * 1000 : null;
  } catch {
    return null;
  }
}

/** Fetches and caches ID tokens from the metadata server (one in-flight request per audience). */
export class IdTokenSource {
  private readonly cache = new Map<string, CachedToken>();
  private readonly inFlight = new Map<string, Promise<string>>();

  constructor(
    private readonly now: () => number = Date.now,
    private readonly fetchImpl: typeof fetch = fetch,
    private readonly env: NodeJS.ProcessEnv = process.env
  ) {}

  async get(audience: string): Promise<string> {
    const cached = this.cache.get(audience);
    if (cached && this.now() < cached.refreshAt) return cached.token;

    const pending = this.inFlight.get(audience);
    if (pending) return pending;

    const request = this.fetchToken(audience).finally(() => this.inFlight.delete(audience));
    this.inFlight.set(audience, request);
    return request;
  }

  private async fetchToken(audience: string): Promise<string> {
    const host = this.env.GCE_METADATA_HOST || "metadata.google.internal";
    const url = `http://${host}/computeMetadata/v1/instance/service-accounts/default/identity?audience=${encodeURIComponent(audience)}`;
    let token: string;
    try {
      const response = await this.fetchImpl(url, {
        headers: { "Metadata-Flavor": "Google" },
        signal: AbortSignal.timeout(METADATA_TIMEOUT_MS),
      });
      if (!response.ok) throw new Error(`metadata server answered ${response.status}`);
      token = (await response.text()).trim();
    } catch (cause) {
      throw new UpstreamAuthError("Could not obtain an identity token for the API", { cause });
    }
    if (token.split(".").length !== 3) {
      throw new UpstreamAuthError("The metadata server did not return an identity token");
    }
    const expiry = expiryMs(token);
    const refreshAt = (expiry ?? this.now() + FALLBACK_TTL_MS) - REFRESH_MARGIN_MS;
    this.cache.set(audience, { token, refreshAt });
    return token;
  }
}

/** The process-wide token source the route handler uses. */
export const idTokens = new IdTokenSource();

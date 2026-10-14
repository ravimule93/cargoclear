/**
 * Server-side API Proxy Route Handler (the BFF).
 *
 * The browser talks to /api/proxy/... only; this handler forwards to the API at the runtime-only API_BASE and streams
 * the answer back (SSE included). Everything that decides HOW it forwards lives in lib/server/proxy.ts:
 *
 * - only GET and POST exist (the API has no other method), and only a fixed list of request headers is forwarded:
 *   cookies, a browser-supplied Authorization and any X-CargoClear-* header never reach the API;
 * - the path must stay below /api/v1 (no `..`, no encoded slash);
 * - with API_AUTH_MODE=google-id-token the API is a private Cloud Run service and every call carries an ID token of
 *   this service's identity;
 * - the end user's IP goes to the API in X-CargoClear-Client-IP (set from what Cloud Run observed, never from the
 *   browser), so the API's rate limits are per user and not one bucket for everybody behind this proxy;
 * - a browser that goes away aborts the upstream request (an SSE stream no longer lingers); ordinary calls have a
 *   deadline just under Cloud Run's request timeout;
 * - the proxy's own errors are fixed texts: no host names or exception messages reach the browser.
 *
 * Environment: see lib/server/proxy.ts. API_BASE is read per request ("force-dynamic") so that Cloud Run's runtime
 * environment, not the image-build environment, supplies it.
 */
import { NextRequest, NextResponse } from "next/server";
import {
  UpstreamAuthError,
  authMode,
  backendBase,
  buildTargetUrl,
  clientIpFrom,
  downstreamResponseHeaders,
  idTokens,
  isStreamPath,
  proxyError,
  requestIdFor,
  trustedProxyHops,
  upstreamRequestHeaders,
} from "@/lib/server/proxy";

export const dynamic = "force-dynamic";

/** Below Cloud Run's 300 s request timeout, so the browser gets a clean 504 instead of a dropped connection. */
const REQUEST_DEADLINE_MS = 280_000;

type RouteContext = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, context: RouteContext) {
  return handleProxy(request, await context.params);
}

export async function POST(request: NextRequest, context: RouteContext) {
  return handleProxy(request, await context.params);
}

async function handleProxy(request: NextRequest, params: { path: string[] }) {
  const requestId = requestIdFor(request.headers);
  const base = backendBase();

  const target = buildTargetUrl(base, params.path ?? [], request.nextUrl.search);
  if (target === null) {
    return NextResponse.json(proxyError("NOT_FOUND", "Resource not found.", requestId), {
      status: 404,
      headers: { "x-request-id": requestId },
    });
  }

  try {
    const idToken = authMode() === "google-id-token" ? await idTokens.get(new URL(base).origin) : null;
    const headers = upstreamRequestHeaders(request.headers, {
      idToken,
      clientIp: clientIpFrom(request.headers, trustedProxyHops()),
      requestId,
    });

    const hasBody = request.method !== "GET" && request.method !== "HEAD";
    const signals: AbortSignal[] = [request.signal];
    if (!isStreamPath(params.path)) signals.push(AbortSignal.timeout(REQUEST_DEADLINE_MS));

    const response = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      signal: AbortSignal.any(signals),
      // @ts-expect-error duplex is required for streaming request body in Node fetch
      duplex: hasBody ? "half" : undefined,
    });

    return new NextResponse(response.body, {
      status: response.status,
      headers: downstreamResponseHeaders(response.headers),
    });
  } catch (err: unknown) {
    if (request.signal.aborted) {
      // the browser went away (closed a tab, left an SSE stream): normal, not an error, and nobody reads this answer
      return new NextResponse(null, { status: 499 });
    }
    // the details go to the server log only
    console.error("api proxy failed", { requestId, error: err instanceof Error ? `${err.name}: ${err.message}` : err });

    if (err instanceof UpstreamAuthError) {
      return NextResponse.json(
        proxyError("PROXY_AUTH_ERROR", "The API could not be reached (service authentication failed).", requestId),
        { status: 502, headers: { "x-request-id": requestId } }
      );
    }
    if (err instanceof Error && err.name === "TimeoutError") {
      return NextResponse.json(proxyError("PROXY_TIMEOUT", "The API did not answer in time.", requestId), {
        status: 504,
        headers: { "x-request-id": requestId },
      });
    }
    return NextResponse.json(proxyError("PROXY_ERROR", "The API could not be reached.", requestId), {
      status: 502,
      headers: { "x-request-id": requestId },
    });
  }
}

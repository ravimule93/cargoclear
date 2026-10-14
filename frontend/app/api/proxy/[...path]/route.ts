/**
 * Server-side API Proxy Route Handler.
 *
 * Environment variables:
 * - API_BASE: The internal URL for the FastAPI backend (default: http://localhost:8080).
 *   Used only by this server-side proxy route. Browser API and SSE traffic
 *   always stays same-origin via /api/proxy.
 */
import { NextRequest, NextResponse } from "next/server";

// Evaluate configuration at request time so Cloud Run's runtime environment,
// rather than Next's image-build environment, supplies the backend URL.
export const dynamic = "force-dynamic";

function backendBase(): string {
  return process.env.API_BASE || "http://localhost:8080";
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return handleProxy(request, await params);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return handleProxy(request, await params);
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return handleProxy(request, await params);
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return handleProxy(request, await params);
}

async function handleProxy(
  request: NextRequest,
  params: { path: string[] }
) {
  try {
    const path = params.path.join("/");
    const targetUrl = new URL(`/api/v1/${path}`, backendBase());

    // Forward query params
    request.nextUrl.searchParams.forEach((val, key) => {
      targetUrl.searchParams.set(key, val);
    });

    const headers = new Headers(request.headers);
    headers.delete("host");

    // Read active auth session from cookie if Authorization header is not explicitly present.
    // Firebase Hosting CDN rewrites forward ONLY the '__session' cookie, so we check both.
    const sessionToken =
      request.cookies.get("__session")?.value ||
      request.cookies.get("cargoclear_session_token")?.value;
    if (sessionToken && !headers.has("authorization")) {
      headers.set("authorization", `Bearer ${sessionToken}`);
    }

    const hasBody = request.method !== "GET" && request.method !== "HEAD";
    const response = await fetch(targetUrl.toString(), {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      // @ts-expect-error duplex is required for streaming request body in Node fetch
      duplex: hasBody ? "half" : undefined,
    });


    return new NextResponse(response.body, {
      status: response.status,
      headers: response.headers,
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Failed to reach backend service";
    return NextResponse.json(
      {
        code: "PROXY_ERROR",
        message,
        detail: null,
      },
      { status: 502 }
    );
  }
}

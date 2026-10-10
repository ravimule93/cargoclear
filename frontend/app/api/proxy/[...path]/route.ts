/**
 * Server-side API Proxy Route Handler.
 *
 * Environment variables:
 * - API_BASE: The internal URL for the FastAPI backend (default: http://localhost:8080).
 *   Used by this server-side proxy route.
 * - NEXT_PUBLIC_API_BASE: The browser-accessible URL for direct backend connections like SSE
 *   (default: http://localhost:8080).
 */
import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.API_BASE || process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8080";

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
  const path = params.path.join("/");
  const targetUrl = new URL(`/api/v1/${path}`, API_BASE);

  // Forward query params
  request.nextUrl.searchParams.forEach((val, key) => {
    targetUrl.searchParams.set(key, val);
  });

  const headers = new Headers(request.headers);
  headers.delete("host");

  try {
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

import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8080";

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
  const targetUrl = new URL(`/api/v1/${path}`, BACKEND_URL);

  // Forward query string
  request.nextUrl.searchParams.forEach((val, key) => {
    targetUrl.searchParams.set(key, val);
  });

  const headers = new Headers(request.headers);
  headers.delete("host");

  try {
    const isFormData = request.headers.get("content-type")?.includes("multipart/form-data");
    const body =
      request.method !== "GET" && request.method !== "HEAD"
        ? isFormData
          ? await request.formData()
          : await request.text()
        : undefined;

    const response = await fetch(targetUrl.toString(), {
      method: request.method,
      headers: isFormData ? undefined : headers,
      body: body as any,
    });

    const responseBody = await response.blob();
    return new NextResponse(responseBody, {
      status: response.status,
      headers: response.headers,
    });
  } catch (err: any) {
    return NextResponse.json(
      {
        code: "PROXY_ERROR",
        message: err.message || "Failed to reach backend service",
        detail: null,
      },
      { status: 502 }
    );
  }
}

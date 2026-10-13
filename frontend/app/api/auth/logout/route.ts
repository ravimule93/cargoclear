import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

function getPublicOrigin(request: NextRequest): string {
  if (process.env.PUBLIC_URL) return process.env.PUBLIC_URL.replace(/\/$/, "");

  const referer = request.headers.get("referer");
  if (referer) {
    try {
      const parsed = new URL(referer);
      if (!parsed.host.includes("localhost") && !parsed.host.includes("127.0.0.1")) {
        return parsed.origin;
      }
    } catch {}
  }

  const forwardedHost = request.headers.get("x-forwarded-host");
  const forwardedProto = request.headers.get("x-forwarded-proto") || "https";
  if (forwardedHost && !forwardedHost.includes("localhost") && !forwardedHost.includes("127.0.0.1")) {
    return `${forwardedProto}://${forwardedHost}`;
  }

  const host = request.headers.get("host");
  if (host && !host.includes("localhost") && !host.includes("127.0.0.1")) {
    return `${forwardedProto}://${host}`;
  }

  return "https://cargoclear-ui-448522365737.asia-south1.run.app";
}

export async function GET(request: NextRequest) {
  const origin = getPublicOrigin(request);
  const returnTo = request.nextUrl.searchParams.get("returnTo") || "/";
  const targetUrl = new URL(returnTo, origin);
  const response = NextResponse.redirect(targetUrl);

  response.cookies.set("cargoclear_session_token", "", {
    path: "/",
    maxAge: 0,
    sameSite: "lax",
  });

  return response;
}

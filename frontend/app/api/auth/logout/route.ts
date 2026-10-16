import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

function getPublicOrigin(request: NextRequest): string {
  if (process.env.PUBLIC_URL) return process.env.PUBLIC_URL.replace(/\/$/, "");

  const forwardedHost = request.headers.get("x-forwarded-host");
  const forwardedProto = request.headers.get("x-forwarded-proto") || "https";
  if (
    forwardedHost &&
    !forwardedHost.includes("localhost") &&
    !forwardedHost.includes("127.0.0.1") &&
    !forwardedHost.includes("google.com")
  ) {
    return `${forwardedProto}://${forwardedHost}`;
  }

  const host = request.headers.get("host");
  if (
    host &&
    !host.includes("localhost") &&
    !host.includes("127.0.0.1") &&
    !host.includes("google.com")
  ) {
    return `${forwardedProto}://${host}`;
  }

  return "https://cargoclear-ui-448522365737.asia-south1.run.app";
}

export async function GET(request: NextRequest) {
  const origin = getPublicOrigin(request);
  const returnTo = request.nextUrl.searchParams.get("returnTo") || "/";
  const targetUrl = new URL(returnTo, origin);
  const response = NextResponse.redirect(targetUrl);

  const isSecure = origin.startsWith("https");
  response.cookies.set("__session", "", {
    path: "/",
    maxAge: 0,
    expires: new Date(0),
    sameSite: "lax",
    secure: isSecure,
  });

  response.cookies.set("cargoclear_session_token", "", {
    path: "/",
    maxAge: 0,
    expires: new Date(0),
    sameSite: "lax",
    secure: isSecure,
  });

  response.cookies.set("cargoclear_google_id_token", "", {
    path: "/",
    maxAge: 0,
    expires: new Date(0),
    sameSite: "lax",
    secure: isSecure,
  });

  return response;
}

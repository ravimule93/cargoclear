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

  return "https://cargoclear-app.web.app";
}

export async function GET(request: NextRequest) {
  const origin = getPublicOrigin(request);
  const returnTo = request.nextUrl.searchParams.get("returnTo") || "/";
  const clientId =
    process.env.GOOGLE_CLIENT_ID ||
    process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ||
    request.nextUrl.searchParams.get("client_id");

  if (!clientId) {
    // If Google Client ID is not configured yet, direct to the OAuth sign-in / configuration page
    const setupUrl = new URL("/auth/signin", origin);
    setupUrl.searchParams.set("reason", "missing_client_id");
    setupUrl.searchParams.set("returnTo", returnTo);
    return NextResponse.redirect(setupUrl);
  }

  const redirectUri = `${origin}/api/auth/callback/google`;
  const stateNonce = crypto.randomUUID();
  const oidcNonce = crypto.randomUUID();

  const statePayload = Buffer.from(
    JSON.stringify({
      nonce: stateNonce,
      returnTo,
    })
  ).toString("base64url");

  const googleAuthUrl = new URL("https://accounts.google.com/o/oauth2/v2/auth");
  googleAuthUrl.searchParams.set("client_id", clientId);
  googleAuthUrl.searchParams.set("redirect_uri", redirectUri);
  googleAuthUrl.searchParams.set("response_type", "code");
  googleAuthUrl.searchParams.set("scope", "openid email profile");
  googleAuthUrl.searchParams.set("access_type", "offline");
  googleAuthUrl.searchParams.set("prompt", "select_account");
  googleAuthUrl.searchParams.set("state", statePayload);
  googleAuthUrl.searchParams.set("nonce", oidcNonce);

  const response = NextResponse.redirect(googleAuthUrl);
  const isSecure = origin.startsWith("https") || process.env.NODE_ENV === "production";

  response.cookies.set("cargoclear_oauth_state", stateNonce, {
    path: "/",
    httpOnly: true,
    secure: isSecure,
    sameSite: "lax",
    maxAge: 600, // 10 minutes
  });

  response.cookies.set("cargoclear_oauth_nonce", oidcNonce, {
    path: "/",
    httpOnly: true,
    secure: isSecure,
    sameSite: "lax",
    maxAge: 600, // 10 minutes
  });

  return response;
}

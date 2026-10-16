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
  const searchParams = request.nextUrl.searchParams;
  const code = searchParams.get("code");
  const state = searchParams.get("state");
  const error = searchParams.get("error");

  if (error || !code) {
    const errorUrl = new URL("/auth/signin", origin);
    errorUrl.searchParams.set("error", error || "authorization_cancelled");
    return NextResponse.redirect(errorUrl);
  }

  // OAuth state is a CSRF control, not merely a carrier for the return URL.
  // The callback must be for the browser that started the sign-in flow.
  const expectedState = request.cookies.get("cargoclear_oauth_state")?.value;
  if (!state || !expectedState || state !== expectedState) {
    const errorUrl = new URL("/auth/signin", origin);
    errorUrl.searchParams.set("error", "invalid_oauth_state");
    return NextResponse.redirect(errorUrl);
  }

  // Parse returnTo from state
  let returnTo = "/";
  try {
    if (state) {
      const decoded = JSON.parse(Buffer.from(state, "base64url").toString("utf-8"));
      if (decoded.returnTo && decoded.returnTo.startsWith("/")) {
        returnTo = decoded.returnTo;
      }
    }
  } catch {
    // ignore state parse errors
  }

  const clientId = process.env.GOOGLE_CLIENT_ID || process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;
  const redirectUri = `${origin}/api/auth/callback/google`;

  try {
    // Exchange authorization code for tokens with Google OAuth
    const tokenResponse = await fetch("https://oauth2.googleapis.com/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        code,
        client_id: clientId || "",
        client_secret: clientSecret || "",
        redirect_uri: redirectUri,
        grant_type: "authorization_code",
      }),
    });

    if (!tokenResponse.ok) {
      const errBody = await tokenResponse.text();
      console.error("[oauth_callback] Token exchange failed:", errBody);
      const errUrl = new URL("/auth/signin", origin);
      errUrl.searchParams.set("error", "token_exchange_failed");
      return NextResponse.redirect(errUrl);
    }

    const tokenData = await tokenResponse.json();
    const idToken = tokenData.id_token;

    if (!idToken) {
      throw new Error("Missing id_token in Google OAuth response");
    }

    // Decode user claims from the verified Google ID token
    let email = "demo-cha@customs.com";
    let name = "Customs Agent";
    try {
      const parts = idToken.split(".");
      if (parts.length >= 2) {
        const payload = JSON.parse(Buffer.from(parts[1], "base64url").toString("utf-8"));
        if (payload.email) email = payload.email.toLowerCase();
        if (payload.name) name = payload.name;
      }
    } catch (e) {
      console.warn("[oauth_callback] Could not parse JWT claims:", e);
    }

    // The API verifies this Google ID token itself. It is HttpOnly so browser
    // JavaScript cannot forge, read, or forward it directly.
    const targetUrl = new URL(returnTo, origin);
    const response = NextResponse.redirect(targetUrl);

    const sessionCookie = {
      path: "/",
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      // Google ID tokens are short-lived. A stale cookie fails verification
      // cleanly rather than creating a seven-day unverified session.
      maxAge: 3600,
    } as const;
    // Firebase Hosting forwards __session through a rewrite. Retain the
    // explicit name too for local/Cloud Run development, but both cookies are
    // HttpOnly and contain the same short-lived Google ID token.
    response.cookies.set("__session", idToken, sessionCookie);
    response.cookies.set("cargoclear_google_id_token", idToken, sessionCookie);

    // Clear state cookie
    response.cookies.set("cargoclear_oauth_state", "", {
      path: "/",
      maxAge: 0,
      sameSite: "lax",
    });

    return response;
  } catch (err: unknown) {
    console.error("[oauth_callback] Error handling callback:", err);
    const errUrl = new URL("/auth/signin", origin);
    errUrl.searchParams.set("error", "authentication_failed");
    return NextResponse.redirect(errUrl);
  }
}

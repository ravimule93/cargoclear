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
  const searchParams = request.nextUrl.searchParams;
  const code = searchParams.get("code");
  const state = searchParams.get("state");
  const error = searchParams.get("error");

  if (error || !code) {
    const errorUrl = new URL("/auth/signin", origin);
    errorUrl.searchParams.set("error", error || "authorization_cancelled");
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

    // Redirect user back to requested page with verified Google ID token cookie
    const targetUrl = new URL(returnTo, origin);
    const response = NextResponse.redirect(targetUrl);

    response.cookies.set("cargoclear_session_token", idToken, {
      path: "/",
      httpOnly: false, // Accessible to client-side identity UI
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      maxAge: 86400 * 7, // 7 days
    });

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

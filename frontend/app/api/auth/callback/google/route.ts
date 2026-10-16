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
  const isSecure = origin.startsWith("https") || process.env.NODE_ENV === "production";
  const searchParams = request.nextUrl.searchParams;
  const code = searchParams.get("code");
  const state = searchParams.get("state");
  const error = searchParams.get("error");

  // 1. If Google returned an error or user cancelled consent
  if (error || !code) {
    console.warn("[oauth_callback] Authorization cancelled or returned error from Google:", error);
    const errorUrl = new URL("/auth/signin", origin);
    errorUrl.searchParams.set("error", error || "authorization_cancelled");
    return NextResponse.redirect(errorUrl);
  }

  // 2. Validate State and CSRF nonce against stored cookie
  const stateCookie = request.cookies.get("cargoclear_oauth_state")?.value;
  let returnTo = "/";
  let stateNonce = "";

  try {
    if (state) {
      const decoded = JSON.parse(Buffer.from(state, "base64url").toString("utf-8"));
      stateNonce = decoded.nonce || "";
      if (
        decoded.returnTo &&
        decoded.returnTo.startsWith("/") &&
        !decoded.returnTo.startsWith("//") &&
        !decoded.returnTo.includes(":")
      ) {
        returnTo = decoded.returnTo;
      }
    }
  } catch (err) {
    console.error("[oauth_callback] Malformed OAuth state parameter:", err);
    const errUrl = new URL("/auth/signin", origin);
    errUrl.searchParams.set("error", "invalid_state");
    return NextResponse.redirect(errUrl);
  }

  if (!stateCookie || !stateNonce || stateCookie !== stateNonce) {
    console.error("[oauth_callback] State CSRF validation failed: cookie vs param mismatch");
    const errUrl = new URL("/auth/signin", origin);
    errUrl.searchParams.set("error", "csrf_validation_failed");
    return NextResponse.redirect(errUrl);
  }

  const clientId = process.env.GOOGLE_CLIENT_ID || process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;
  const redirectUri = `${origin}/api/auth/callback/google`;

  if (!clientId || !clientSecret) {
    console.error("[oauth_callback] Missing Google OAuth credentials in environment");
    const errUrl = new URL("/auth/signin", origin);
    errUrl.searchParams.set("error", "missing_oauth_config");
    return NextResponse.redirect(errUrl);
  }

  try {
    // 3. Exchange authorization code for tokens directly with Google's OAuth 2.0 token endpoint
    const tokenResponse = await fetch("https://oauth2.googleapis.com/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        code,
        client_id: clientId,
        client_secret: clientSecret,
        redirect_uri: redirectUri,
        grant_type: "authorization_code",
      }),
    });

    if (!tokenResponse.ok) {
      const errBody = await tokenResponse.text();
      console.error("[oauth_callback] Token exchange failed with Google:", errBody);
      const errUrl = new URL("/auth/signin", origin);
      errUrl.searchParams.set("error", "token_exchange_failed");
      return NextResponse.redirect(errUrl);
    }

    const tokenData = await tokenResponse.json();
    const idToken = tokenData.id_token;

    if (!idToken) {
      console.error("[oauth_callback] Missing id_token in Google token response");
      const errUrl = new URL("/auth/signin", origin);
      errUrl.searchParams.set("error", "missing_id_token");
      return NextResponse.redirect(errUrl);
    }

    // 4. Cryptographically verify the Google ID token via Google's tokeninfo API
    const verifyResponse = await fetch(
      `https://oauth2.googleapis.com/tokeninfo?id_token=${encodeURIComponent(idToken)}`
    );
    if (!verifyResponse.ok) {
      const verifyErr = await verifyResponse.text();
      console.error("[oauth_callback] Google ID token cryptographic verification failed:", verifyErr);
      const errUrl = new URL("/auth/signin", origin);
      errUrl.searchParams.set("error", "token_verification_failed");
      return NextResponse.redirect(errUrl);
    }

    const verifiedClaims = await verifyResponse.json();

    // Verify audience
    if (verifiedClaims.aud !== clientId) {
      console.error("[oauth_callback] Audience mismatch:", { tokenAud: verifiedClaims.aud, expected: clientId });
      const errUrl = new URL("/auth/signin", origin);
      errUrl.searchParams.set("error", "token_audience_mismatch");
      return NextResponse.redirect(errUrl);
    }

    // Verify issuer
    if (verifiedClaims.iss !== "https://accounts.google.com" && verifiedClaims.iss !== "accounts.google.com") {
      console.error("[oauth_callback] Issuer mismatch:", verifiedClaims.iss);
      const errUrl = new URL("/auth/signin", origin);
      errUrl.searchParams.set("error", "token_issuer_mismatch");
      return NextResponse.redirect(errUrl);
    }

    // Verify email_verified
    if (verifiedClaims.email_verified !== "true" && verifiedClaims.email_verified !== true) {
      console.error("[oauth_callback] Email not verified by Google:", verifiedClaims.email);
      const errUrl = new URL("/auth/signin", origin);
      errUrl.searchParams.set("error", "email_not_verified");
      return NextResponse.redirect(errUrl);
    }

    // Verify nonce if present
    const expectedNonce = request.cookies.get("cargoclear_oauth_nonce")?.value;
    if (expectedNonce && verifiedClaims.nonce && verifiedClaims.nonce !== expectedNonce) {
      console.error("[oauth_callback] Nonce mismatch:", { tokenNonce: verifiedClaims.nonce, expected: expectedNonce });
      const errUrl = new URL("/auth/signin", origin);
      errUrl.searchParams.set("error", "nonce_mismatch");
      return NextResponse.redirect(errUrl);
    }

    const email = (verifiedClaims.email || "").toLowerCase();
    const name = verifiedClaims.name || email.split("@")[0] || "Customs Agent";
    const sub = verifiedClaims.sub;

    if (!email || !sub) {
      console.error("[oauth_callback] Incomplete Google identity claims:", verifiedClaims);
      const errUrl = new URL("/auth/signin", origin);
      errUrl.searchParams.set("error", "incomplete_identity");
      return NextResponse.redirect(errUrl);
    }

    // 5. Establish Genuine Authenticated Session
    // Store the verified Google ID token directly in session cookies.
    // The server-side BFF proxy (/api/proxy) forwards this token in X-CargoClear-User-Token,
    // where the backend cryptographically validates it against Google's public JWKS certificates.
    const targetUrl = new URL(returnTo, origin);
    const response = NextResponse.redirect(targetUrl);

    // Set __session (required by Firebase Hosting CDN rewrites and server-side BFF proxy)
    response.cookies.set("__session", idToken, {
      path: "/",
      httpOnly: false,
      secure: isSecure,
      sameSite: "lax",
      maxAge: 86400 * 7, // 7 days
    });

    response.cookies.set("cargoclear_session_token", idToken, {
      path: "/",
      httpOnly: false,
      secure: isSecure,
      sameSite: "lax",
      maxAge: 86400 * 7,
    });

    response.cookies.set("cargoclear_google_id_token", idToken, {
      path: "/",
      httpOnly: false,
      secure: isSecure,
      sameSite: "lax",
      maxAge: 86400 * 7,
    });

    // Client-readable user identity attributes for navigation headers and avatar
    response.cookies.set("cargoclear_user_email", email, {
      path: "/",
      httpOnly: false,
      secure: isSecure,
      sameSite: "lax",
      maxAge: 86400 * 7,
    });

    response.cookies.set("cargoclear_user_name", name, {
      path: "/",
      httpOnly: false,
      secure: isSecure,
      sameSite: "lax",
      maxAge: 86400 * 7,
    });

    // 6. Clean up temporary OAuth verification cookies
    response.cookies.set("cargoclear_oauth_state", "", {
      path: "/",
      maxAge: 0,
      expires: new Date(0),
      sameSite: "lax",
      secure: isSecure,
    });

    response.cookies.set("cargoclear_oauth_nonce", "", {
      path: "/",
      maxAge: 0,
      expires: new Date(0),
      sameSite: "lax",
      secure: isSecure,
    });

    return response;
  } catch (err: unknown) {
    console.error("[oauth_callback] Unexpected error during Google authentication:", err);
    const errUrl = new URL("/auth/signin", origin);
    errUrl.searchParams.set("error", "authentication_failed");
    return NextResponse.redirect(errUrl);
  }
}

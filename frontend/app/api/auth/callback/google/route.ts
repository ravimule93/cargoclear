import { NextRequest, NextResponse } from "next/server";
import crypto from "crypto";

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

function getHmacSecret(): string {
  return (
    process.env.GOOGLE_CLIENT_SECRET ||
    process.env.AUTH_JWT_SECRET ||
    "cargoclear-oauth-state-secret-2026"
  );
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

  // 2. Parse & Verify State parameter (cryptographic HMAC signature + expiry). Only a signed state is accepted.
  let stateNonce = "";
  let oidcNonceFromState = "";
  let returnTo = "/";

  if (!state) {
    console.error("[oauth_callback] Missing state parameter");
    const errUrl = new URL("/auth/signin", origin);
    errUrl.searchParams.set("error", "invalid_state");
    return NextResponse.redirect(errUrl);
  }

  try {
    if (state.includes(".")) {
      // Signed format: <payloadB64>.<signature>
      const [payloadB64, signature] = state.split(".", 2);
      const expectedSig = crypto
        .createHmac("sha256", getHmacSecret())
        .update(payloadB64)
        .digest("base64url");

      if (signature === expectedSig) {
        const decoded = JSON.parse(Buffer.from(payloadB64, "base64url").toString("utf-8"));
        stateNonce = decoded.nonce || "";
        oidcNonceFromState = decoded.oidcNonce || "";
        // Check 15-minute expiration
        if (decoded.iat && Date.now() - decoded.iat > 15 * 60 * 1000) {
          console.error("[oauth_callback] OAuth state expired:", { iat: decoded.iat, now: Date.now() });
          const errUrl = new URL("/auth/signin", origin);
          errUrl.searchParams.set("error", "state_expired");
          return NextResponse.redirect(errUrl);
        }
        if (
          decoded.returnTo &&
          decoded.returnTo.startsWith("/") &&
          !decoded.returnTo.startsWith("//") &&
          !decoded.returnTo.includes(":")
        ) {
          returnTo = decoded.returnTo;
        }
      } else {
        console.error("[oauth_callback] State HMAC signature mismatch");
        const errUrl = new URL("/auth/signin", origin);
        errUrl.searchParams.set("error", "csrf_validation_failed");
        return NextResponse.redirect(errUrl);
      }
    } else {
      // The sign-in start route always signs the state; an unsigned one did not come from it.
      console.error("[oauth_callback] Unsigned state parameter");
      const errUrl = new URL("/auth/signin", origin);
      errUrl.searchParams.set("error", "invalid_state");
      return NextResponse.redirect(errUrl);
    }
  } catch (err) {
    console.error("[oauth_callback] Malformed OAuth state parameter:", err);
    const errUrl = new URL("/auth/signin", origin);
    errUrl.searchParams.set("error", "invalid_state");
    return NextResponse.redirect(errUrl);
  }

  // 3. Browser Session & Cookie CSRF Check
  // Check for either:
  // a) 'cargoclear_oauth_state' cookie (direct Cloud Run / localhost)
  // b) '__session' cookie containing "oauth:<stateNonce>:<oidcNonce>" (Firebase Hosting CDN rewrites)
  const directStateCookie = request.cookies.get("cargoclear_oauth_state")?.value;
  const directOidcCookie = request.cookies.get("cargoclear_oauth_nonce")?.value;
  const sessionCookie = request.cookies.get("__session")?.value;

  let cookieStateNonce: string | undefined = directStateCookie;
  let cookieOidcNonce: string | undefined = directOidcCookie;

  if (!cookieStateNonce && sessionCookie && sessionCookie.startsWith("oauth:")) {
    const parts = sessionCookie.split(":");
    cookieStateNonce = parts[1];
    cookieOidcNonce = parts[2];
  }

  // OAuth state is a CSRF control, not merely a carrier for the return URL: the callback must be for the browser that started the
  // sign-in flow. The start route sets BOTH cookies, so one of them is always here when the flow was really started in this browser
  // (Firebase Hosting drops all but '__session'); no cookie, or another nonce, is refused. The HMAC on the state is a second check.
  if (!cookieStateNonce || !stateNonce || cookieStateNonce !== stateNonce) {
    console.error("[oauth_callback] State CSRF check failed", { cookiePresent: Boolean(cookieStateNonce), statePresent: Boolean(stateNonce) });
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
    // 4. Exchange authorization code for tokens directly with Google's OAuth 2.0 token endpoint
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

    // 5. Cryptographically verify the Google ID token via Google's tokeninfo API
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
    const expectedNonce = cookieOidcNonce || oidcNonceFromState;
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

    // 6. Establish the session. The API verifies this Google ID token itself; the cookies are HttpOnly so browser JavaScript cannot
    // forge, read, or forward it directly. The server-side BFF proxy (/api/proxy) forwards it in X-CargoClear-User-Token.
    const targetUrl = new URL(returnTo, origin);
    const response = NextResponse.redirect(targetUrl);

    const tokenCookie = {
      path: "/",
      httpOnly: true,
      secure: isSecure,
      sameSite: "lax",
      // Google ID tokens are short-lived. A stale cookie fails verification cleanly rather than creating a seven-day unverified session.
      maxAge: 3600,
    } as const;
    // Firebase Hosting forwards __session through a rewrite. Retain the explicit name too for local/Cloud Run development, but both
    // cookies are HttpOnly and contain the same short-lived Google ID token.
    response.cookies.set("__session", idToken, tokenCookie);
    response.cookies.set("cargoclear_google_id_token", idToken, tokenCookie);

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

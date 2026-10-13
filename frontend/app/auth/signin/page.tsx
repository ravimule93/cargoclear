"use client";

import { useSearchParams } from "next/navigation";
import { useState, Suspense } from "react";
import Link from "next/link";

function SignInContent() {
  const searchParams = useSearchParams();
  const reason = searchParams.get("reason");
  const error = searchParams.get("error");
  const returnTo = searchParams.get("returnTo") || "/";

  const [email, setEmail] = useState("");
  const [customClientId, setCustomClientId] = useState("");

  const handleCommercialLogin = (targetEmail: string) => {
    if (!targetEmail.trim()) return;
    const cleanEmail = targetEmail.trim().toLowerCase();
    document.cookie = `cargoclear_session_token=mock-jwt-${cleanEmail}-LICENSED_CHA; path=/; max-age=86400; SameSite=Lax`;
    window.location.href = returnTo;
  };

  const handleGoogleSignInWithCustomClient = (e: React.FormEvent) => {
    e.preventDefault();
    if (!customClientId.trim()) return;
    window.location.href = `/api/auth/signin/google?client_id=${encodeURIComponent(customClientId.trim())}&returnTo=${encodeURIComponent(returnTo)}`;
  };

  return (
    <main className="mx-auto flex min-h-dvh max-w-lg flex-col justify-center gap-6 p-6">
      <div className="rounded-xl border border-[var(--cc-border-strong)] bg-[var(--cc-surface)] p-6 shadow-xl space-y-6">
        <header className="space-y-1 text-center">
          <div className="inline-flex items-center justify-center h-10 w-10 rounded-full bg-[var(--cc-surface-2)] text-xl mb-2">
            🛃
          </div>
          <h1 className="text-xl font-bold tracking-tight text-[var(--cc-text)]">
            CargoClear Commercial SSO
          </h1>
          <p className="text-xs text-[var(--cc-text-muted)]">
            Single Sign-On and multi-tenant access for Customs House Agents & Brokers
          </p>
        </header>

        {error && (
          <div role="alert" className="rounded-lg bg-red-500/10 border border-red-500/30 p-3 text-xs text-red-500 text-center">
            Authentication error: {error}. Please try again.
          </div>
        )}

        {/* Primary OAuth Button: Google Identity Provider */}
        <div className="space-y-3">
          <a
            href={`/api/auth/signin/google?returnTo=${encodeURIComponent(returnTo)}`}
            className="flex items-center justify-center gap-3 w-full rounded-lg border border-[var(--cc-border-strong)] bg-white dark:bg-[#1f1f1f] py-2.5 px-4 text-xs font-semibold text-gray-800 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-[#2a2a2a] shadow-xs transition-colors cursor-pointer"
          >
            <svg className="h-4 w-4" viewBox="0 0 24 24">
              <path
                fill="#4285F4"
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
              />
              <path
                fill="#34A853"
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              />
              <path
                fill="#FBBC05"
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
              />
              <path
                fill="#EA4335"
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
              />
            </svg>
            <span>Continue with Google</span>
          </a>

          {reason === "missing_client_id" && (
            <div className="rounded-lg bg-amber-500/10 border border-amber-500/30 p-3 space-y-2 text-[11px] text-amber-700 dark:text-amber-300">
              <p className="font-semibold flex items-center gap-1">
                <span>⚠️</span> Google OAuth Client ID Not Yet Configured in Cloud Run
              </p>
              <p>
                To enable live Google redirection, configure your OAuth Client in Google Cloud Console with authorized redirect URI:
              </p>
              <code className="block rounded bg-black/10 dark:bg-black/30 p-1.5 font-mono text-[10px] select-all break-all">
                https://cargoclear-ui-448522365737.asia-south1.run.app/api/auth/callback/google
              </code>
              <form onSubmit={handleGoogleSignInWithCustomClient} className="pt-1 flex gap-1.5">
                <input
                  type="text"
                  placeholder="Paste OAuth Client ID here..."
                  value={customClientId}
                  onChange={(e) => setCustomClientId(e.target.value)}
                  className="flex-1 rounded border border-amber-500/40 bg-[var(--cc-surface)] px-2 py-1 text-[10px] text-[var(--cc-text)]"
                />
                <button
                  type="submit"
                  className="rounded bg-amber-600 px-2.5 py-1 text-[10px] font-semibold text-white hover:bg-amber-700"
                >
                  Connect
                </button>
              </form>
            </div>
          )}
        </div>

        <div className="relative flex items-center justify-center">
          <div className="w-full border-t border-[var(--cc-border)]" />
          <span className="bg-[var(--cc-surface)] px-2 text-[10px] uppercase tracking-wider text-[var(--cc-text-muted)] absolute">
            or commercial email
          </span>
        </div>

        {/* Commercial Corporate CHA Email */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleCommercialLogin(email);
          }}
          className="space-y-3"
        >
          <div>
            <label htmlFor="email-input" className="block text-[11px] font-medium text-[var(--cc-text-muted)] mb-1">
              Customs Broker / CHA Corporate Email
            </label>
            <input
              id="email-input"
              type="email"
              required
              placeholder="e.g. broker@customs.com or ops@dhl.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded border border-[var(--cc-border-strong)] bg-[var(--cc-surface-2)] px-3 py-2 text-xs text-[var(--cc-text)] focus:outline-hidden focus:ring-1 focus:ring-[var(--cc-focus)]"
            />
          </div>
          <button
            type="submit"
            className="w-full rounded bg-[var(--cc-focus)] py-2 text-xs font-semibold text-white hover:opacity-90 cursor-pointer transition-opacity"
          >
            Sign In with Corporate SSO
          </button>
        </form>

        {/* 1-Click Quick Demo Presets */}
        <div className="pt-2 border-t border-[var(--cc-border)]">
          <span className="block text-[10px] text-[var(--cc-text-muted)] mb-1.5">
            Quick demo presets (1-click sign in):
          </span>
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() => handleCommercialLogin("demo-cha@customs.com")}
              className="rounded bg-[var(--cc-surface-2)] border border-[var(--cc-border)] px-2.5 py-1 text-[11px] font-medium text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] cursor-pointer"
            >
              🏢 customs.com
            </button>
            <button
              type="button"
              onClick={() => handleCommercialLogin("agent@dhl.com")}
              className="rounded bg-[var(--cc-surface-2)] border border-[var(--cc-border)] px-2.5 py-1 text-[11px] font-medium text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] cursor-pointer"
            >
              📦 dhl.com
            </button>
            <button
              type="button"
              onClick={() => handleCommercialLogin("broker@fedex.com")}
              className="rounded bg-[var(--cc-surface-2)] border border-[var(--cc-border)] px-2.5 py-1 text-[11px] font-medium text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] cursor-pointer"
            >
              ✈️ fedex.com
            </button>
          </div>
        </div>

        <div className="text-center pt-2">
          <Link
            href="/"
            className="text-[11px] text-[var(--cc-text-muted)] hover:text-[var(--cc-text)] underline"
          >
            ← Back to start
          </Link>
        </div>
      </div>
    </main>
  );
}

export default function SignInPage() {
  return (
    <Suspense fallback={<div className="p-6 text-center text-xs">Loading authentication...</div>}>
      <SignInContent />
    </Suspense>
  );
}

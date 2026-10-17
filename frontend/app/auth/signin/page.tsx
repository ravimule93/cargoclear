"use client";

import { useSearchParams } from "next/navigation";
import { useState, Suspense } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { toErrorEnvelope } from "@/lib/errors";

function SignInContent() {
  const searchParams = useSearchParams();
  const reason = searchParams.get("reason");
  const queryError = searchParams.get("error");
  const initialTab = searchParams.get("tab") === "signup" ? "signup" : "signin";
  const returnTo = searchParams.get("returnTo") || "/";
  const initialEmail = searchParams.get("email") || "";

  const [activeTab, setActiveTab] = useState<"signin" | "signup">(initialTab);
  const [customClientId, setCustomClientId] = useState("");

  // Sign In form state
  const [signInEmail, setSignInEmail] = useState(initialEmail);
  const [signInPassword, setSignInPassword] = useState("");
  const getErrorMessage = (err: string | null) => {
    if (!err) return null;
    switch (err) {
      case "csrf_validation_failed":
        return "Security verification failed (OAuth state mismatch). Please try signing in again.";
      case "state_expired":
        return "Sign-in session timed out. Please try signing in again.";
      case "invalid_state":
        return "Invalid sign-in request. Please try signing in again.";
      case "token_exchange_failed":
        return "Failed to exchange authorization code with Google. Please retry.";
      case "token_verification_failed":
        return "Google ID token cryptographic validation failed. Access denied.";
      case "token_audience_mismatch":
        return "Google token was not issued for this application.";
      case "email_not_verified":
        return "Your Google email address is not verified by Google. Access denied.";
      case "authorization_cancelled":
        return "Google sign-in was cancelled.";
      case "missing_oauth_config":
        return "Google OAuth Client credentials are not configured.";
      default:
        return err;
    }
  };

  const [signInLoading, setSignInLoading] = useState(false);
  const [signInError, setSignInError] = useState<string | null>(getErrorMessage(queryError));

  // Sign Up form state
  const [signUpName, setSignUpName] = useState("");
  const [signUpEmail, setSignUpEmail] = useState(initialEmail);
  const [signUpOrg, setSignUpOrg] = useState("");
  const [signUpRole, setSignUpRole] = useState<"LICENSED_CHA" | "OPERATOR" | "AUDITOR">("LICENSED_CHA");
  const [signUpPassword, setSignUpPassword] = useState("");
  const [signUpConfirmPassword, setSignUpConfirmPassword] = useState("");
  const [signUpLoading, setSignUpLoading] = useState(false);
  const [signUpError, setSignUpError] = useState<string | null>(null);
  const [signUpSuccessMsg, setSignUpSuccessMsg] = useState<string | null>(null);

  // Save session cookie and navigate
  const finalizeAuth = (token: string) => {
    const isHttps = typeof window !== "undefined" && window.location.protocol === "https:";
    const secureFlag = isHttps ? "; Secure" : "";
    document.cookie = `__session=${token}; path=/; max-age=604800; SameSite=Lax${secureFlag}`;
    document.cookie = `cargoclear_session_token=${token}; path=/; max-age=604800; SameSite=Lax${secureFlag}`;
    window.location.href = returnTo;
  };

  const handleSignInSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!signInEmail.trim() || !signInPassword.trim()) return;

    setSignInLoading(true);
    setSignInError(null);

    try {
      const res = await api.signIn({
        email: signInEmail.trim().toLowerCase(),
        password: signInPassword,
      });
      finalizeAuth(res.token);
    } catch (err: unknown) {
      setSignInLoading(false);
      const env = toErrorEnvelope(err);
      if (env.code === "HTTP_404" || env.code === "NOT_FOUND") {
        setSignInError(`No account found for "${signInEmail}". Please click "Sign Up" above to register.`);
      } else if (env.code === "HTTP_401" || env.code === "UNAUTHORIZED" || env.code === "AUTHENTICATION_ERROR") {
        setSignInError("Invalid email or password. Please verify your credentials.");
      } else {
        setSignInError(env.message || "Failed to sign in. Please try again.");
      }
    }
  };

  const handleSignUpSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!signUpName.trim() || !signUpEmail.trim() || !signUpPassword.trim()) {
      setSignUpError("Please fill in all required fields.");
      return;
    }

    if (signUpPassword !== signUpConfirmPassword) {
      setSignUpError("Passwords do not match. Please re-enter.");
      return;
    }

    if (signUpPassword.length < 6) {
      setSignUpError("Password must be at least 6 characters.");
      return;
    }

    setSignUpLoading(true);
    setSignUpError(null);
    setSignUpSuccessMsg(null);

    try {
      const res = await api.signUp({
        name: signUpName.trim(),
        email: signUpEmail.trim().toLowerCase(),
        organization: signUpOrg.trim() || undefined,
        role: signUpRole,
        password: signUpPassword,
      });

      setSignUpSuccessMsg("Account successfully registered! Logging you into customs workspace...");
      setTimeout(() => {
        finalizeAuth(res.token);
      }, 700);
    } catch (err: unknown) {
      setSignUpLoading(false);
      const env = toErrorEnvelope(err);
      if (env.code === "HTTP_409" || env.code === "CONFLICT") {
        setSignUpError(`Account already exists for "${signUpEmail}". Switched to Sign In.`);
        setSignInEmail(signUpEmail);
        setActiveTab("signin");
      } else {
        setSignUpError(env.message || "Registration failed. Please try again.");
      }
    }
  };

  const handleQuickDemoLogin = (email: string) => {
    const clean = email.trim().toLowerCase();
    finalizeAuth(`mock-jwt-${clean}-LICENSED_CHA`);
  };

  const handleGoogleSignInWithCustomClient = (e: React.FormEvent) => {
    e.preventDefault();
    if (!customClientId.trim()) return;
    window.location.href = `/api/auth/signin/google?client_id=${encodeURIComponent(customClientId.trim())}&returnTo=${encodeURIComponent(returnTo)}`;
  };

  return (
    <main className="mx-auto flex min-h-dvh max-w-lg flex-col justify-center gap-6 p-3 sm:p-6">
      <div className="rounded-xl border border-[var(--cc-border-strong)] bg-[var(--cc-surface)] p-4 sm:p-6 shadow-xl space-y-6">
        <header className="space-y-1 text-center">
          <div className="inline-flex items-center justify-center h-10 w-10 rounded-full bg-[var(--cc-surface-2)] text-xl mb-2">
            🛃
          </div>
          <h1 className="text-xl font-bold tracking-tight text-[var(--cc-text)]">
            CargoClear Commercial Identity
          </h1>
          <p className="text-xs text-[var(--cc-text-muted)]">
            Secure Single Sign-On & User Registration for Customs Clearance
          </p>
        </header>

        {/* Tab Switcher */}
        <div className="grid grid-cols-2 rounded-lg bg-[var(--cc-surface-2)] p-1 border border-[var(--cc-border)]">
          <button
            type="button"
            onClick={() => {
              setActiveTab("signin");
              setSignInError(null);
            }}
            className={`rounded-md py-1.5 text-xs font-semibold transition-all cursor-pointer ${
              activeTab === "signin"
                ? "bg-[var(--cc-surface)] text-[var(--cc-text)] shadow-xs"
                : "text-[var(--cc-text-muted)] hover:text-[var(--cc-text)]"
            }`}
          >
            🔑 Sign In
          </button>
          <button
            type="button"
            onClick={() => {
              setActiveTab("signup");
              setSignUpError(null);
              if (signInEmail && !signUpEmail) {
                setSignUpEmail(signInEmail);
              }
            }}
            className={`rounded-md py-1.5 text-xs font-semibold transition-all cursor-pointer ${
              activeTab === "signup"
                ? "bg-[var(--cc-surface)] text-[var(--cc-text)] shadow-xs"
                : "text-[var(--cc-text-muted)] hover:text-[var(--cc-text)]"
            }`}
          >
            📝 Sign Up (New User)
          </button>
        </div>

        {/* TAB 1: SIGN IN */}
        {activeTab === "signin" && (
          <div className="space-y-5">
            {signInError && (
              <div role="alert" className="rounded-lg bg-red-500/10 border border-red-500/30 p-3 text-xs text-red-500">
                <div className="flex items-center justify-between">
                  <span>{signInError}</span>
                  {signInError.includes("Sign Up") && (
                    <button
                      type="button"
                      onClick={() => {
                        setSignUpEmail(signInEmail);
                        setActiveTab("signup");
                      }}
                      className="ml-2 font-bold underline hover:opacity-80 cursor-pointer whitespace-nowrap"
                    >
                      Go to Sign Up →
                    </button>
                  )}
                </div>
              </div>
            )}

            {/* Google SSO Button */}
            <div className="space-y-3">
              <a
                href={`/api/auth/signin/google?returnTo=${encodeURIComponent(returnTo)}`}
                className="flex items-center justify-center gap-3 w-full rounded-lg border border-[var(--cc-border-strong)] bg-white dark:bg-[#1f1f1f] py-2.5 px-4 text-xs font-semibold text-gray-800 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-[#2a2a2a] shadow-xs transition-colors cursor-pointer"
              >
                <svg className="h-4 w-4" viewBox="0 0 24 24">
                  <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                  <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                  <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" />
                  <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" />
                </svg>
                <span>Continue with Google SSO</span>
              </a>

              {reason === "missing_client_id" && (
                <div className="rounded-lg bg-amber-500/10 border border-amber-500/30 p-3 space-y-2 text-[11px] text-amber-700 dark:text-amber-300">
                  <p className="font-semibold flex items-center gap-1">
                    <span>⚠️</span> Google OAuth Client ID Pending in Cloud Run Environment
                  </p>
                  <p>
                    To activate Google authentication, authorize this redirect URI in Google Cloud Console:
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
                      className="rounded bg-amber-600 px-2.5 py-1 text-[10px] font-semibold text-white hover:bg-amber-700 cursor-pointer"
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
                or sign in with email & password
              </span>
            </div>

            {/* Email + Password Form */}
            <form onSubmit={handleSignInSubmit} className="space-y-3">
              <div>
                <label className="block text-[11px] font-medium text-[var(--cc-text-muted)] mb-1">
                  Corporate CHA Email
                </label>
                <input
                  type="email"
                  required
                  placeholder="agent@customs.com"
                  value={signInEmail}
                  onChange={(e) => setSignInEmail(e.target.value)}
                  className="w-full rounded border border-[var(--cc-border-strong)] bg-[var(--cc-surface-2)] px-3 py-2 text-xs text-[var(--cc-text)] focus:outline-hidden focus:ring-1 focus:ring-[var(--cc-focus)]"
                />
              </div>

              <div>
                <label className="block text-[11px] font-medium text-[var(--cc-text-muted)] mb-1">
                  Password
                </label>
                <input
                  type="password"
                  required
                  placeholder="Enter your password"
                  value={signInPassword}
                  onChange={(e) => setSignInPassword(e.target.value)}
                  className="w-full rounded border border-[var(--cc-border-strong)] bg-[var(--cc-surface-2)] px-3 py-2 text-xs text-[var(--cc-text)] focus:outline-hidden focus:ring-1 focus:ring-[var(--cc-focus)]"
                />
              </div>

              <button
                type="submit"
                disabled={signInLoading}
                className="w-full rounded bg-[var(--cc-focus)] py-2 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50 cursor-pointer transition-opacity flex items-center justify-center gap-1.5"
              >
                {signInLoading ? (
                  <>
                    <span className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
                    <span>Verifying credentials...</span>
                  </>
                ) : (
                  <span>Sign In</span>
                )}
              </button>
            </form>

            {/* 1-Click Demo Presets */}
            <div className="pt-2 border-t border-[var(--cc-border)]">
              <span className="block text-[10px] text-[var(--cc-text-muted)] mb-1.5">
                Quick demo presets (1-click sign in):
              </span>
              <div className="flex flex-wrap gap-1.5">
                <button
                  type="button"
                  onClick={() => handleQuickDemoLogin("demo-cha@customs.com")}
                  className="rounded bg-[var(--cc-surface-2)] border border-[var(--cc-border)] px-2.5 py-1 text-[11px] font-medium text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] cursor-pointer"
                >
                  🏢 customs.com
                </button>
                <button
                  type="button"
                  onClick={() => handleQuickDemoLogin("agent@dhl.com")}
                  className="rounded bg-[var(--cc-surface-2)] border border-[var(--cc-border)] px-2.5 py-1 text-[11px] font-medium text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] cursor-pointer"
                >
                  📦 dhl.com
                </button>
                <button
                  type="button"
                  onClick={() => handleQuickDemoLogin("broker@fedex.com")}
                  className="rounded bg-[var(--cc-surface-2)] border border-[var(--cc-border)] px-2.5 py-1 text-[11px] font-medium text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] cursor-pointer"
                >
                  ✈️ fedex.com
                </button>
              </div>
            </div>
          </div>
        )}

        {/* TAB 2: SIGN UP (NEW USER) */}
        {activeTab === "signup" && (
          <div className="space-y-5">
            {signUpError && (
              <div role="alert" className="rounded-lg bg-red-500/10 border border-red-500/30 p-3 text-xs text-red-500">
                {signUpError}
              </div>
            )}
            {signUpSuccessMsg && (
              <div role="status" className="rounded-lg bg-emerald-500/10 border border-emerald-500/30 p-3 text-xs text-emerald-600 dark:text-emerald-400">
                {signUpSuccessMsg}
              </div>
            )}

            {/* Google 1-Click Sign Up */}
            <div className="space-y-3">
              <a
                href={`/api/auth/signin/google?returnTo=${encodeURIComponent(returnTo)}`}
                className="flex items-center justify-center gap-3 w-full rounded-lg border border-[var(--cc-border-strong)] bg-white dark:bg-[#1f1f1f] py-2.5 px-4 text-xs font-semibold text-gray-800 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-[#2a2a2a] shadow-xs transition-colors cursor-pointer"
              >
                <svg className="h-4 w-4" viewBox="0 0 24 24">
                  <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                  <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                  <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" />
                  <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" />
                </svg>
                <span>Sign Up with Google SSO</span>
              </a>
            </div>

            <div className="relative flex items-center justify-center">
              <div className="w-full border-t border-[var(--cc-border)]" />
              <span className="bg-[var(--cc-surface)] px-2 text-[10px] uppercase tracking-wider text-[var(--cc-text-muted)] absolute">
                or register with corporate details
              </span>
            </div>

            {/* Registration Form */}
            <form onSubmit={handleSignUpSubmit} className="space-y-3">
              <div>
                <label className="block text-[11px] font-medium text-[var(--cc-text-muted)] mb-1">
                  Full Name *
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. John Doe"
                  value={signUpName}
                  onChange={(e) => setSignUpName(e.target.value)}
                  className="w-full rounded border border-[var(--cc-border-strong)] bg-[var(--cc-surface-2)] px-3 py-2 text-xs text-[var(--cc-text)] focus:outline-hidden focus:ring-1 focus:ring-[var(--cc-focus)]"
                />
              </div>

              <div>
                <label className="block text-[11px] font-medium text-[var(--cc-text-muted)] mb-1">
                  Corporate CHA / Customs Email *
                </label>
                <input
                  type="email"
                  required
                  placeholder="e.g. john@customs.com"
                  value={signUpEmail}
                  onChange={(e) => setSignUpEmail(e.target.value)}
                  className="w-full rounded border border-[var(--cc-border-strong)] bg-[var(--cc-surface-2)] px-3 py-2 text-xs text-[var(--cc-text)] focus:outline-hidden focus:ring-1 focus:ring-[var(--cc-focus)]"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-medium text-[var(--cc-text-muted)] mb-1">
                    Organization / Brokerage
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. Apex Customs Ltd"
                    value={signUpOrg}
                    onChange={(e) => setSignUpOrg(e.target.value)}
                    className="w-full rounded border border-[var(--cc-border-strong)] bg-[var(--cc-surface-2)] px-3 py-2 text-xs text-[var(--cc-text)] focus:outline-hidden focus:ring-1 focus:ring-[var(--cc-focus)]"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-[var(--cc-text-muted)] mb-1">
                    Customs Role
                  </label>
                  <select
                    value={signUpRole}
                    onChange={(e) => setSignUpRole(e.target.value as any)}
                    className="w-full rounded border border-[var(--cc-border-strong)] bg-[var(--cc-surface-2)] px-3 py-2 text-xs text-[var(--cc-text)] focus:outline-hidden focus:ring-1 focus:ring-[var(--cc-focus)]"
                  >
                    <option value="LICENSED_CHA">Licensed CHA Broker</option>
                    <option value="OPERATOR">Cargo Clearance Agent</option>
                    <option value="AUDITOR">Customs Auditor</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-medium text-[var(--cc-text-muted)] mb-1">
                    Password (min 6 chars) *
                  </label>
                  <input
                    type="password"
                    required
                    minLength={6}
                    placeholder="••••••••"
                    value={signUpPassword}
                    onChange={(e) => setSignUpPassword(e.target.value)}
                    className="w-full rounded border border-[var(--cc-border-strong)] bg-[var(--cc-surface-2)] px-3 py-2 text-xs text-[var(--cc-text)] focus:outline-hidden focus:ring-1 focus:ring-[var(--cc-focus)]"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-[var(--cc-text-muted)] mb-1">
                    Confirm Password *
                  </label>
                  <input
                    type="password"
                    required
                    minLength={6}
                    placeholder="••••••••"
                    value={signUpConfirmPassword}
                    onChange={(e) => setSignUpConfirmPassword(e.target.value)}
                    className="w-full rounded border border-[var(--cc-border-strong)] bg-[var(--cc-surface-2)] px-3 py-2 text-xs text-[var(--cc-text)] focus:outline-hidden focus:ring-1 focus:ring-[var(--cc-focus)]"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={signUpLoading}
                className="w-full rounded bg-[var(--cc-focus)] py-2 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50 cursor-pointer transition-opacity flex items-center justify-center gap-1.5"
              >
                {signUpLoading ? (
                  <>
                    <span className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
                    <span>Creating account...</span>
                  </>
                ) : (
                  <span>Create Account & Register</span>
                )}
              </button>
            </form>
          </div>
        )}

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

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { toErrorEnvelope } from "@/lib/errors";
import { useMeta } from "@/lib/hooks/useMeta";
import { ModeBadge } from "@/components/shell/ModeBadge";
import { UserMenu } from "@/components/shell/UserMenu";
import type { Bundle } from "@/lib/types";

type Pending = "empty" | "demo" | "demo-d" | null;

/** The destinations the rules cover: the checks and the duty estimate depend on where the goods are going. */
const DESTINATIONS = [
  { code: "SG", label: "Singapore (SG)" },
  { code: "IN", label: "India (IN)" },
] as const;
export const dynamic = "force-dynamic";
export const revalidate = 0;
type Destination = (typeof DESTINATIONS)[number]["code"];

export default function Home() {
  const router = useRouter();
  const { meta, loading: metaLoading, error: metaError, retry: retryMeta } = useMeta();
  const [pending, setPending] = useState<Pending>(null);
  const [error, setError] = useState<string | null>(null);
  const [destination, setDestination] = useState<Destination>("SG");

  const start = async (kind: Exclude<Pending, null>, create: () => Promise<Bundle>) => {
    if (meta?.auth?.enabled && !meta?.user) {
      setError("Authentication required: Please enter your CHA corporate email below to sign in before creating a bundle.");
      return;
    }
    setPending(kind);
    setError(null);
    try {
      const bundle = await create();
      router.push(`/workbench/${bundle.id}`);
    } catch (err: unknown) {
      const env = toErrorEnvelope(err);
      if (env.code === "UNAUTHORIZED") {
        setError("Authentication required: Please sign in with your corporate email below to continue.");
      } else {
        setError(env.message);
      }
      setPending(null);
    }
  };

  const showDemo = meta?.app_mode === "demo";

  return (
    <main className="mx-auto flex min-h-dvh max-w-xl flex-col justify-center gap-6 p-6">
      <header className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold tracking-tight text-[var(--cc-text)]">CargoClear-JAPAC</h1>
          <div className="flex items-center gap-2">
            <ModeBadge />
            <UserMenu
              user={meta?.user ?? null}
              onLogin={(email) => {
                const token = `mock-jwt-${email}-LICENSED_CHA`;
                document.cookie = `__session=${token}; path=/; max-age=86400; SameSite=Lax`;
                document.cookie = `cargoclear_session_token=${token}; path=/; max-age=86400; SameSite=Lax`;
                window.location.reload();
              }}
              onLogout={() => {
                document.cookie = "__session=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT";
                document.cookie = "cargoclear_session_token=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT";
                window.location.href = "/api/auth/logout";
              }}
            />
          </div>
        </div>
        <p className="text-sm text-[var(--cc-text-muted)] leading-relaxed">
          Pre-submission customs document assessment. Create a bundle, add trade documents and run
          the analysis. Decision support only: the authorised CHA decides.
        </p>
      </header>

      {meta?.auth?.enabled && !meta?.user && (
        <div className="rounded-lg border border-[var(--cc-focus)]/30 bg-[var(--cc-surface-2)] p-4 shadow-xs space-y-3">
          <div>
            <h2 className="text-sm font-semibold text-[var(--cc-text)] flex items-center gap-1.5">
              <span>🔐</span> Commercial Single Sign-On (SSO) & Registration
            </h2>
            <p className="text-xs text-[var(--cc-text-muted)] mt-1">
              Sign in with your corporate Google Workspace account, corporate email/password, or register a new customs user account.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
            <Link
              href="/auth/signin?tab=signin"
              className="flex items-center justify-center gap-1.5 rounded-lg border border-[var(--cc-border-strong)] bg-[var(--cc-surface)] p-2.5 text-xs font-semibold text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] transition-colors text-center shadow-2xs"
            >
              <span>🔑 Sign In to Account</span>
            </Link>
            <Link
              href="/auth/signin?tab=signup"
              className="flex items-center justify-center gap-1.5 rounded-lg bg-[var(--cc-focus)] p-2.5 text-xs font-semibold text-white hover:opacity-90 transition-opacity text-center shadow-2xs"
            >
              <span>📝 Create New Account</span>
            </Link>
          </div>

          <a
            href="/api/auth/signin/google"
            className="flex items-center justify-center gap-2.5 w-full rounded-lg border border-[var(--cc-border-strong)] bg-white dark:bg-[#1f1f1f] py-2 px-3 text-xs font-semibold text-gray-800 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-[#2a2a2a] shadow-xs transition-colors cursor-pointer"
          >
            <svg className="h-4 w-4" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" />
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" />
            </svg>
            <span>Continue with Google SSO</span>
          </a>

          <div className="relative flex items-center justify-center">
            <div className="w-full border-t border-[var(--cc-border)]" />
            <span className="bg-[var(--cc-surface-2)] px-2 text-[10px] uppercase tracking-wider text-[var(--cc-text-muted)] absolute">
              or quick demo access
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-1.5 pt-1">
            <span className="text-[10px] text-[var(--cc-text-muted)]">1-Click presets:</span>
            <button
              type="button"
              onClick={() => {
                const token = "mock-jwt-demo-cha@customs.com-LICENSED_CHA";
                document.cookie = `__session=${token}; path=/; max-age=86400; SameSite=Lax`;
                document.cookie = `cargoclear_session_token=${token}; path=/; max-age=86400; SameSite=Lax`;
                window.location.reload();
              }}
              className="text-[10px] rounded bg-[var(--cc-surface)] border border-[var(--cc-border)] px-2 py-0.5 text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] cursor-pointer"
            >
              🏢 customs.com
            </button>
            <button
              type="button"
              onClick={() => {
                const token = "mock-jwt-agent@dhl.com-LICENSED_CHA";
                document.cookie = `__session=${token}; path=/; max-age=86400; SameSite=Lax`;
                document.cookie = `cargoclear_session_token=${token}; path=/; max-age=86400; SameSite=Lax`;
                window.location.reload();
              }}
              className="text-[10px] rounded bg-[var(--cc-surface)] border border-[var(--cc-border)] px-2 py-0.5 text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] cursor-pointer"
            >
              📦 dhl.com
            </button>
            <button
              type="button"
              onClick={() => {
                const token = "mock-jwt-broker@fedex.com-LICENSED_CHA";
                document.cookie = `__session=${token}; path=/; max-age=86400; SameSite=Lax`;
                document.cookie = `cargoclear_session_token=${token}; path=/; max-age=86400; SameSite=Lax`;
                window.location.reload();
              }}
              className="text-[10px] rounded bg-[var(--cc-surface)] border border-[var(--cc-border)] px-2 py-0.5 text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] cursor-pointer"
            >
              ✈️ fedex.com
            </button>
          </div>
        </div>
      )}

      {meta?.user && (
        <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3 flex items-center justify-between text-xs">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-[var(--cc-text)]">
              Signed in as <strong className="font-semibold">{meta.user.email}</strong>
            </span>
            <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-mono text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
              Tenant: {meta.user.tenant_id}
            </span>
          </div>
          <button
            type="button"
            onClick={() => {
              document.cookie = "__session=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT";
              document.cookie = "cargoclear_session_token=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT";
              window.location.href = "/api/auth/logout";
            }}
            className="text-[11px] text-[var(--cc-text-muted)] hover:text-red-500 underline cursor-pointer"
          >
            Sign out
          </button>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-[var(--cc-text-muted)]">
          Destination
          <select
            data-testid="destination-select"
            value={destination}
            disabled={pending !== null}
            onChange={(e) => setDestination(e.target.value as Destination)}
            className="rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] bg-transparent px-2 py-1.5 text-sm text-[var(--cc-text)] cursor-pointer"
          >
            {DESTINATIONS.map((d) => (
              <option key={d.code} value={d.code}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={pending !== null}
          onClick={() => start("empty", () => api.createBundle(undefined, destination))}
          className="rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] px-4 py-2 text-sm font-semibold text-[var(--cc-text)] hover:bg-[var(--cc-surface-2)] disabled:opacity-50 cursor-pointer"
        >
          {pending === "empty" ? "Creating bundle..." : "New empty bundle"}
        </button>

        {showDemo && (
          <button
            type="button"
            disabled={pending !== null}
            onClick={() => start("demo", () => api.createCaseCDemo())}
            className="rounded-[var(--cc-radius)] bg-[var(--cc-focus)] px-4 py-2 text-sm font-semibold text-white hover:brightness-90 disabled:opacity-50 cursor-pointer"
          >
            {pending === "demo" ? "Starting demo..." : "Start Case C demo"}
          </button>
        )}

        {showDemo && (
          <button
            type="button"
            disabled={pending !== null}
            onClick={() => start("demo-d", () => api.createCaseDDemo())}
            className="rounded-[var(--cc-radius)] border border-[var(--cc-focus)] px-4 py-2 text-sm font-semibold text-[var(--cc-focus)] hover:bg-[var(--cc-surface-2)] disabled:opacity-50 cursor-pointer"
          >
            {pending === "demo-d" ? "Starting demo..." : "Start Case D demo (India import)"}
          </button>
        )}
      </div>

      {metaLoading && (
        <p role="status" className="text-xs text-[var(--cc-text-muted)]">
          Checking backend mode...
        </p>
      )}

      {metaError && (
        <div role="alert" className="flex items-center gap-3 text-xs text-[var(--cc-err)]">
          <span>Could not reach the backend: {metaError}</span>
          <button
            type="button"
            onClick={retryMeta}
            className="rounded border border-[var(--cc-border-strong)] px-2 py-0.5 text-[var(--cc-text)] cursor-pointer"
          >
            Retry
          </button>
        </div>
      )}

      {error && (
        <div role="alert" className="text-xs font-medium text-[var(--cc-err)]">
          {error}
        </div>
      )}

      {showDemo && (
        <div className="flex flex-col gap-1.5 text-[11px] text-[var(--cc-text-muted)] leading-relaxed">
          <p>
            Demo mode: the Case C demo loads an invoice, bill of lading and packing list for a seamless-pipe
            shipment (HS 7304) from India to Singapore; add the mill test certificate to reach a compliant
            verdict. Extraction uses synthetic fixtures keyed on filename, not a real document reading.
          </p>
          <p>
            Case D is an import into India: all four documents are loaded and the certificate&apos;s chemistry
            contradicts the declared HS code. It also shows an anti-dumping warning and an indicative duty
            estimate. Every name, number and rate in the demo is invented or illustrative.
          </p>
        </div>
      )}
    </main>
  );
}

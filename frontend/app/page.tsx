"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { toErrorEnvelope } from "@/lib/errors";
import { useMeta } from "@/lib/hooks/useMeta";
import { ModeBadge } from "@/components/shell/ModeBadge";
import { ThemeToggle } from "@/components/shell/ThemeToggle";
import { UserMenu } from "@/components/shell/UserMenu";
import { StatusPill } from "@/components/assess/StatusPill";
import { DEMO_ACCOUNTS, demoSignIn, signOut } from "@/lib/session";
import type { Bundle } from "@/lib/types";

type Pending = "empty" | "demo" | "demo-d" | null;

/** The destinations the rules cover: the checks and the duty estimate depend on where the goods are going. */
const DESTINATIONS = [
  { code: "SG", label: "Singapore (SG)" },
  { code: "IN", label: "India (IN)" },
] as const;
type Destination = (typeof DESTINATIONS)[number]["code"];

function RecentBundlesList({
  bundles,
  loading,
  error,
  onRefresh,
}: {
  bundles: Bundle[];
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}) {
  return (
    <section className="rounded-xl border border-[var(--cc-border)] bg-[var(--cc-surface)] p-4 shadow-[var(--cc-shadow-1)] space-y-3" aria-labelledby="recent-cases-heading">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-[var(--cc-text)] flex items-center gap-1.5">
          <span id="recent-cases-heading">Recent cases</span>
        </h2>
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          className="text-xs text-[var(--cc-text-muted)] hover:text-[var(--cc-text)] disabled:opacity-50 cursor-pointer flex items-center gap-1"
        >
          {loading ? "Refreshing..." : "↻ Refresh"}
        </button>
      </div>

      {loading && bundles.length === 0 && (
        <p className="text-xs text-[var(--cc-text-muted)] py-3 text-center">Loading recent bundles...</p>
      )}

      {error && (
        <p className="text-xs text-red-500 py-1">{error}</p>
      )}

      {!loading && bundles.length === 0 && (
        <div className="rounded border border-dashed border-[var(--cc-border-strong)] p-4 text-center">
          <p className="text-xs text-[var(--cc-text-muted)]">
            No bundles created yet in this workspace.
          </p>
          <p className="text-[11px] text-[var(--cc-text-muted)] mt-1">
            Click <strong>&quot;New empty bundle&quot;</strong> or choose a demo case above to run your first clearance assessment.
          </p>
        </div>
      )}

      {bundles.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b border-[var(--cc-border)] text-[11px] text-[var(--cc-text-muted)] uppercase tracking-wider font-semibold">
                <th className="py-2 px-2.5">Bundle ID</th>
                <th className="py-2 px-2.5">Destination</th>
                <th className="py-2 px-2.5">Documents</th>
                <th className="py-2 px-2.5">Status</th>
                <th className="py-2 px-2.5">Created</th>
                <th className="py-2 px-2.5 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--cc-border)]">
              {bundles.map((b) => (
                <tr key={b.id} className="hover:bg-[var(--cc-surface-3)] transition-colors">
                  <td className="py-2 px-2.5 font-mono font-medium text-[var(--cc-text)]">
                    <Link href={`/workbench/${b.id}`} className="hover:underline text-[var(--cc-focus)]">
                      {b.id}
                    </Link>
                    {b.reference && (
                      <span className="block text-[10px] text-[var(--cc-text-muted)] font-sans">{b.reference}</span>
                    )}
                  </td>
                  <td className="py-2 px-2.5 text-[var(--cc-text-muted)]">
                    <span className="rounded bg-[var(--cc-surface)] px-1.5 py-0.5 border border-[var(--cc-border)] font-semibold">
                      {b.destination_country}
                    </span>
                  </td>
                  <td className="py-2 px-2.5 text-[var(--cc-text-muted)]">
                    {b.documents && b.documents.length > 0 ? (
                      <span
                        title={b.documents.map((d) => d.filename || d.doc_type).join("\n")}
                        className="inline-flex items-center gap-1.5 rounded bg-[var(--cc-surface)] px-2 py-0.5 border border-[var(--cc-border)] font-medium text-[11px] text-[var(--cc-text)] cursor-help shadow-2xs"
                      >
                        <span aria-hidden="true">📄</span>
                        <span>{b.documents.length} {b.documents.length === 1 ? "doc" : "docs"}</span>
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[11px] text-[var(--cc-text-muted)]">
                        <span>0 docs</span>
                      </span>
                    )}
                  </td>
                  <td className="py-2 px-2.5">
                    <StatusPill status={b.status} />
                  </td>
                  <td className="py-2 px-2.5 text-[var(--cc-text-muted)] text-[11px]">
                    {b.created_at ? new Date(b.created_at).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" }) : "—"}
                  </td>
                  <td className="py-2 px-2.5 text-right">
                    <Link
                      href={`/workbench/${b.id}`}
                      className="inline-flex items-center gap-1 rounded bg-[var(--cc-surface)] border border-[var(--cc-border-strong)] px-2.5 py-1 text-[11px] font-medium text-[var(--cc-text)] hover:bg-[var(--cc-focus)] hover:text-white transition-colors"
                    >
                      Open →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default function Home() {
  const router = useRouter();
  const { meta, loading: metaLoading, error: metaError, retry: retryMeta } = useMeta();
  const [pending, setPending] = useState<Pending>(null);
  const [error, setError] = useState<string | null>(null);
  const [destination, setDestination] = useState<Destination>("SG");

  const [bundles, setBundles] = useState<Bundle[]>([]);
  const [bundlesLoading, setBundlesLoading] = useState(false);
  const [bundlesError, setBundlesError] = useState<string | null>(null);

  const loadBundles = useCallback(async () => {
    setBundlesLoading(true);
    setBundlesError(null);
    try {
      const data = await api.listBundles(15);
      setBundles(data);
    } catch (err: unknown) {
      console.warn("Could not load recent bundles", err);
      setBundlesError("Could not load recent bundles");
    } finally {
      setBundlesLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!meta?.auth?.enabled || meta?.user) {
      loadBundles();
    }
  }, [meta, loadBundles]);

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
    <main className="mx-auto flex min-h-dvh max-w-5xl flex-col gap-6 px-4 py-5 sm:px-6 lg:py-8">
      <header className="flex flex-col gap-3 border-b border-[var(--cc-border)] pb-5 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[.15em] text-[var(--cc-text-subtle)]">JAPAC customs workspace</p>
            <h1 className="mt-1 text-2xl font-bold tracking-tight text-[var(--cc-text)]">CargoClear</h1>
            <p className="mt-1 max-w-xl text-sm leading-relaxed text-[var(--cc-text-muted)]">Assess a trade-document bundle, resolve evidence gaps, and prepare a supported declaration.</p>
          </div>
          <div className="flex items-center gap-2">
            <ModeBadge />
            <ThemeToggle showLabel />
            <UserMenu
              user={meta?.user ?? null}
              onLogin={(email) => {
                if (demoSignIn(email, meta?.app_mode)) window.location.reload();
              }}
              onLogout={signOut}
            />
          </div>
        </div>
      </header>

      {meta?.auth?.enabled && !meta?.user && (
        <div className="rounded-lg border border-[var(--cc-focus)]/30 bg-[var(--cc-surface-2)] p-4 shadow-xs space-y-3">
          <div>
            <h2 className="text-sm font-semibold text-[var(--cc-text)] flex items-center gap-1.5">
              <span>🔐</span> Commercial Single Sign-On (SSO) & Registration
            </h2>
            <p className="text-xs text-[var(--cc-text-muted)] mt-1">
              Sign in with Google, register a customs workspace account, or use 1-click quick presets below.
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
            {DEMO_ACCOUNTS.map((account) => (
              <button
                key={account.email}
                type="button"
                onClick={() => { if (demoSignIn(account.email, meta?.app_mode)) window.location.reload(); }}
                className="text-[10px] rounded bg-[var(--cc-surface)] border border-[var(--cc-border)] px-2 py-0.5 text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] cursor-pointer"
              >
                {account.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Bundle creation & Assessment Hub */}
      {(!meta?.auth?.enabled || meta?.user) && (
        <div className="space-y-4">
          {/* Custom Assessment Card */}
          <section className="rounded-xl border border-[var(--cc-border)] bg-[var(--cc-surface)] p-5 shadow-[var(--cc-shadow-1)]">
            <p className="text-[10px] font-bold uppercase tracking-[.12em] text-[var(--cc-text-subtle)]">Primary task</p>
            <h2 className="mt-1 text-lg font-semibold text-[var(--cc-text)]">Start a trade assessment</h2>
            <p className="mt-1 text-xs text-[var(--cc-text-muted)]">Choose a destination and open a case. Documents and analysis come next.</p>
            <div className="flex flex-wrap items-center gap-3 mt-3 pt-2 border-t border-[var(--cc-border)]">
              <label className="flex items-center gap-2 text-xs font-medium text-[var(--cc-text-muted)]">
                <span>Destination:</span>
                <select
                  data-testid="destination-select"
                  value={destination}
                  disabled={pending !== null}
                  onChange={(e) => setDestination(e.target.value as Destination)}
                  className="rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] bg-[var(--cc-surface)] px-2.5 py-1.5 text-xs font-semibold text-[var(--cc-text)] cursor-pointer"
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
                className="rounded-[var(--cc-radius)] bg-[var(--cc-surface)] border border-[var(--cc-border-strong)] px-4 py-1.5 text-xs font-bold text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] disabled:opacity-50 transition-colors cursor-pointer ml-auto"
              >
                {pending === "empty" ? "Creating bundle..." : "New empty bundle"}
              </button>
            </div>
          </section>

          {/* Pre-Configured Benchmark Scenarios */}
          {showDemo && (
            <div className="rounded-lg border border-[var(--cc-border)] bg-[var(--cc-surface-2)] p-4 shadow-xs space-y-3">
              <div>
                <h2 className="text-sm font-semibold text-[var(--cc-text)] flex items-center gap-1.5">
                  <span>🧪</span> Pre-Loaded Benchmark Scenarios
                </h2>
                <p className="text-xs text-[var(--cc-text-muted)] mt-0.5">
                  Launch verified cross-border trade packages to evaluate multimodal AI extraction, discrepancy engines, and tariff calculation.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
                {/* Case C Card */}
                <div className="rounded-md border border-[var(--cc-border)] bg-[var(--cc-surface)] p-3 flex flex-col justify-between gap-2.5">
                  <div className="space-y-1">
                    <div className="flex items-center justify-between gap-1">
                      <span className="font-bold text-xs text-[var(--cc-text)]">Case C: Seamless Pipe (SG)</span>
                      <span className="text-[10px] font-bold px-1.5 py-0.2 rounded bg-amber-100 dark:bg-amber-950/60 text-amber-900 dark:text-amber-200 border border-amber-500/30">
                        Missing MTC
                      </span>
                    </div>
                    <p className="text-[11px] text-[var(--cc-text-muted)] leading-relaxed">
                      Invoice, BoL & Packing List for HS 7304. Demonstrates missing regulatory document detection and dynamic upload to achieve compliance.
                    </p>
                  </div>
                  <button
                    type="button"
                    disabled={pending !== null}
                    onClick={() => start("demo", () => api.createCaseCDemo())}
                    className="w-full rounded-[var(--cc-radius)] bg-[var(--cc-focus)] px-3 py-1.5 text-xs font-bold text-white hover:brightness-90 disabled:opacity-50 transition-all cursor-pointer text-center"
                  >
                    {pending === "demo" ? "Starting demo..." : "Start Case C demo"}
                  </button>
                </div>

                {/* Case D Card */}
                <div className="rounded-md border border-[var(--cc-border)] bg-[var(--cc-surface)] p-3 flex flex-col justify-between gap-2.5">
                  <div className="space-y-1">
                    <div className="flex items-center justify-between gap-1">
                      <span className="font-bold text-xs text-[var(--cc-text)]">Case D: Line Pipe (IN)</span>
                      <span className="text-[10px] font-bold px-1.5 py-0.2 rounded bg-red-100 dark:bg-red-950/60 text-red-900 dark:text-red-200 border border-red-500/30">
                        Chemistry & Tariff
                      </span>
                    </div>
                    <p className="text-[11px] text-[var(--cc-text-muted)] leading-relaxed">
                      Complete 4-doc package into India. Demonstrates metallurgical chemistry contradiction (HS Note 1), anti-dumping checks, and duty estimate.
                    </p>
                  </div>
                  <button
                    type="button"
                    disabled={pending !== null}
                    onClick={() => start("demo-d", () => api.createCaseDDemo())}
                    className="w-full rounded-[var(--cc-radius)] border border-[var(--cc-focus)] px-3 py-1.5 text-xs font-bold text-[var(--cc-focus)] hover:bg-[var(--cc-surface-2)] disabled:opacity-50 transition-all cursor-pointer text-center"
                  >
                    {pending === "demo-d" ? "Starting demo..." : "Start Case D demo (India import)"}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {(!meta?.auth?.enabled || meta?.user) && (
        <RecentBundlesList
          bundles={bundles}
          loading={bundlesLoading}
          error={bundlesError}
          onRefresh={loadBundles}
        />
      )}

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

"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { api } from "@/lib/api";
import { AUTHENTICATION_REQUIRED_MESSAGE, toErrorEnvelope } from "@/lib/errors";
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
        <p role="alert" className="text-xs text-[var(--cc-err)] py-1">{error}</p>
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
                      className="inline-flex items-center gap-1 rounded bg-[var(--cc-surface)] border border-[var(--cc-border-strong)] px-2.5 py-1 text-[11px] font-medium text-[var(--cc-text)] hover:bg-[var(--cc-action)] hover:text-white transition-colors"
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
  const errorRef = useRef<HTMLDivElement>(null);
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
      const message = toErrorEnvelope(err).message;
      setBundlesError(message === AUTHENTICATION_REQUIRED_MESSAGE ? message : "Could not load recent bundles");
    } finally {
      setBundlesLoading(false);
    }
  }, []);

  useEffect(() => {
    if (meta && (!meta.auth?.enabled || meta.user)) {
      loadBundles();
    }
  }, [meta, loadBundles]);

  const start = async (kind: Exclude<Pending, null>, create: () => Promise<Bundle>) => {
    if (!meta) return;
    if (meta?.auth?.enabled && !meta?.user) {
      setError(AUTHENTICATION_REQUIRED_MESSAGE);
      requestAnimationFrame(() => errorRef.current?.focus());
      return;
    }
    setPending(kind);
    setError(null);
    try {
      const bundle = await create();
      router.push(`/workbench/${bundle.id}`);
    } catch (err: unknown) {
      const env = toErrorEnvelope(err);
      if (env.code === "UNAUTHORIZED" || env.code === "HTTP_401") {
        setError(AUTHENTICATION_REQUIRED_MESSAGE);
      } else {
        setError(env.message);
      }
      setPending(null);
      requestAnimationFrame(() => errorRef.current?.focus());
    }
  };

  const showDemo = meta?.app_mode === "demo";
  const needsSignIn = Boolean(meta?.auth?.enabled && !meta.user);

  useEffect(() => {
    if (!meta || window.location.hash !== "#new-bundle") return;
    const setup = document.getElementById("new-bundle");
    setup?.scrollIntoView({ block: "start" });
    setup?.focus({ preventScroll: true });
  }, [meta]);

  return (
    <main className="mx-auto flex min-h-dvh max-w-5xl flex-col gap-6 px-4 py-5 sm:px-6 lg:py-8">
      <header className="flex flex-col gap-4 border-b border-[var(--cc-border)] pb-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <p className="text-[10px] font-bold uppercase tracking-[.15em] text-[var(--cc-text-subtle)]">JAPAC customs workspace</p>
          <h1 className="mt-1 flex items-center gap-2 text-2xl font-bold tracking-tight text-[var(--cc-text)]"><Image src="/cargoclear-logo.webp" alt="" width={28} height={28} aria-hidden="true" className="rounded-md" />CargoClear</h1>
          <p className="mt-1 max-w-xl text-sm leading-relaxed text-[var(--cc-text-muted)]">Assess a trade-document bundle, resolve evidence gaps, and prepare a supported declaration.</p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
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
      </header>

      {error && (
        <div ref={errorRef} tabIndex={-1} role="alert" className="flex flex-wrap items-center gap-3 rounded border border-[var(--cc-err)] p-3 text-sm font-medium text-[var(--cc-err)]">
          <span>{error}</span>
          {error === AUTHENTICATION_REQUIRED_MESSAGE && (
            <Link href="/auth/signin?returnTo=%2F" className="font-semibold underline">Sign in</Link>
          )}
        </div>
      )}

      {/* Bundle creation & Assessment Hub */}
      {meta && (
        <div className={`grid items-stretch gap-4 ${needsSignIn ? "lg:grid-cols-[minmax(0,1fr)_20rem]" : ""}`}>
          {/* Custom Assessment Card */}
          <section id="new-bundle" tabIndex={-1} aria-labelledby="start-assessment-heading" className="flex flex-col justify-between gap-5 rounded-xl border border-[var(--cc-border)] bg-[var(--cc-surface)] p-5 shadow-[var(--cc-shadow-1)]">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[.12em] text-[var(--cc-text-subtle)]">Primary task</p>
              <h2 id="start-assessment-heading" className="mt-1 text-lg font-semibold text-[var(--cc-text)]">Start a trade assessment</h2>
              <p className="mt-1 text-xs leading-relaxed text-[var(--cc-text-muted)]">Choose a destination and open a case. Upload and classify documents, then run an assessment.</p>
            </div>
            <div className="flex flex-wrap items-center gap-3 pt-3 border-t border-[var(--cc-border)]">
              <div className="space-y-1">
                <label className="flex items-center gap-2 text-xs font-medium text-[var(--cc-text-muted)]">
                  <span>Destination:</span>
                  <select
                    data-testid="destination-select"
                    value={destination}
                    disabled={pending !== null || needsSignIn}
                    aria-describedby={needsSignIn ? "destination-sign-in-hint" : undefined}
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
                {needsSignIn && <p id="destination-sign-in-hint" className="text-xs text-[var(--cc-text-muted)]">Sign in to change destination.</p>}
              </div>
              <button
                type="button"
                disabled={pending !== null}
                onClick={() => start("empty", () => api.createBundle(undefined, destination))}
                className="cc-button cc-button-primary ml-auto"
              >
                {pending === "empty" ? "Creating bundle..." : "New empty bundle"}
              </button>
            </div>
          </section>

        {needsSignIn && (
          <section aria-labelledby="workspace-access-heading" className="min-w-0 space-y-2 rounded-xl border border-[var(--cc-border)] bg-[var(--cc-surface-2)] p-4">
            <div>
              <h2 id="workspace-access-heading" className="text-sm font-semibold text-[var(--cc-text)]">Workspace access</h2>
              <p className="mt-1 text-xs leading-relaxed text-[var(--cc-text-muted)]">Sign in or choose a demo account.</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Link href="/auth/signin?tab=signin" className="inline-flex min-h-7 items-center text-xs font-semibold text-[var(--cc-focus)] underline underline-offset-2">Sign in to account</Link>
              <Link href="/auth/signin?tab=signup" className="inline-flex min-h-7 items-center text-xs font-semibold text-[var(--cc-text)] underline underline-offset-2">Create account</Link>
            </div>
            <a href="/api/auth/signin/google" className="cc-button w-full">
              <svg aria-hidden="true" className="h-4 w-4 shrink-0" viewBox="0 0 24 24">
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" />
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" />
              </svg>
              Continue with Google SSO
            </a>
            <div className="space-y-1.5 border-t border-[var(--cc-border)] pt-2">
              <p className="text-[11px] text-[var(--cc-text-muted)]">Demo accounts</p>
              <div className="flex flex-wrap gap-1.5">
                {DEMO_ACCOUNTS.map((account) => (
                  <button key={account.email} type="button" onClick={() => { if (demoSignIn(account.email, meta.app_mode)) window.location.reload(); }} className="cc-button min-h-8 px-2">
                    {account.label}
                  </button>
                ))}
              </div>
            </div>
          </section>
        )}
        </div>
      )}

      {showDemo && (
        <section aria-labelledby="demo-cases-heading" className="space-y-4">
          <div className="space-y-1">
            <h2 id="demo-cases-heading" className="text-base font-semibold text-[var(--cc-text)]">Explore demo cases</h2>
            <p className="text-xs leading-relaxed text-[var(--cc-text-muted)]">Synthetic examples of the evidence-resolution workflow. Extraction uses filename-keyed fixtures, not real PDF reading.{needsSignIn && " Sign in to start a case."}</p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <article aria-labelledby="case-c-heading" className="flex flex-col gap-4 rounded-xl border border-[var(--cc-border)] bg-[var(--cc-surface)] p-5 shadow-[var(--cc-shadow-1)]">
              <div className="space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs font-medium text-[var(--cc-text-subtle)]">India → Singapore · HS 7304</p>
                  <span className="rounded border border-[var(--cc-warn-bd)] bg-[var(--cc-warn-bg)] px-2 py-0.5 text-[11px] font-semibold text-[var(--cc-warn)]">Missing MTC</span>
                </div>
                <h3 id="case-c-heading" className="text-sm font-semibold text-[var(--cc-text)]">Case C: Seamless Pipe (SG)</h3>
                <p className="text-xs leading-relaxed text-[var(--cc-text-muted)]">Invoice, bill of lading and packing list for a seamless-pipe shipment. Add the mill test certificate and reassess to resolve the missing evidence.</p>
              </div>
              <div className="mt-auto space-y-3 border-t border-[var(--cc-border)] pt-3">
                <p className="text-xs text-[var(--cc-text-subtle)]">3 documents preloaded · Evidence-upload workflow</p>
                <button type="button" disabled={pending !== null} onClick={() => start("demo", () => api.createCaseCDemo())} className="cc-button cc-button-primary w-full">
                  {pending === "demo" ? "Starting demo..." : "Start Case C demo"}
                </button>
              </div>
            </article>
            <article aria-labelledby="case-d-heading" className="flex flex-col gap-4 rounded-xl border border-[var(--cc-border)] bg-[var(--cc-surface)] p-5 shadow-[var(--cc-shadow-1)]">
              <div className="space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs font-medium text-[var(--cc-text-subtle)]">India import · Chemistry &amp; tariff</p>
                  <span className="rounded border border-[var(--cc-err-bd)] bg-[var(--cc-err-bg)] px-2 py-0.5 text-[11px] font-semibold text-[var(--cc-err)]">Material contradiction</span>
                </div>
                <h3 id="case-d-heading" className="text-sm font-semibold text-[var(--cc-text)]">Case D: Line Pipe (IN)</h3>
                <p className="text-xs leading-relaxed text-[var(--cc-text-muted)]">A complete four-document package. Review certificate chemistry against HS Note 1, an anti-dumping warning, and the indicative duty estimate.</p>
              </div>
              <div className="mt-auto space-y-3 border-t border-[var(--cc-border)] pt-3">
                <p className="text-xs text-[var(--cc-text-subtle)]">4 documents preloaded · Contradiction-review workflow</p>
                <button type="button" disabled={pending !== null} onClick={() => start("demo-d", () => api.createCaseDDemo())} className="cc-button w-full">
                  {pending === "demo-d" ? "Starting demo..." : "Start Case D demo (India import)"}
                </button>
              </div>
            </article>
          </div>
        </section>
      )}

      {meta && (!meta.auth?.enabled || meta.user) && (
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

      {showDemo && (
        <footer className="mt-auto border-t border-[var(--cc-border)] pt-4 text-[11px] leading-relaxed text-[var(--cc-text-muted)]">
          <p id="demo-data-disclaimer">Synthetic demo data. Duty estimates are illustrative; the authorised agent makes the final decision.</p>
          <details className="mt-1.5">
            <summary className="w-fit min-h-6 cursor-pointer font-medium text-[var(--cc-text)]">About demo data</summary>
            <div className="mt-2 space-y-1.5">
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
          </details>
        </footer>
      )}
    </main>
  );
}

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { toErrorEnvelope } from "@/lib/errors";
import { useMeta } from "@/lib/hooks/useMeta";
import { ModeBadge } from "@/components/shell/ModeBadge";
import { UserMenu } from "@/components/shell/UserMenu";
import type { Bundle } from "@/lib/types";

type Pending = "empty" | "demo" | null;

export default function Home() {
  const router = useRouter();
  const { meta, loading: metaLoading, error: metaError, retry: retryMeta } = useMeta();
  const [pending, setPending] = useState<Pending>(null);
  const [error, setError] = useState<string | null>(null);

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
                document.cookie = `cargoclear_session_token=mock-jwt-${email}-LICENSED_CHA; path=/; max-age=86400; SameSite=Lax`;
                window.location.reload();
              }}
              onLogout={() => {
                document.cookie = `cargoclear_session_token=; path=/; max-age=0; SameSite=Lax`;
                window.location.reload();
              }}
            />
          </div>
        </div>
        <p className="text-sm text-[var(--cc-text-muted)] leading-relaxed">
          Pre-submission adversarial customs adjudicator. Create a bundle, add trade documents and run
          the analysis. Decision support only: the authorised CHA decides.
        </p>
      </header>

      {meta?.auth?.enabled && !meta?.user && (
        <div className="rounded-lg border border-[var(--cc-focus)]/30 bg-[var(--cc-surface-2)] p-4 shadow-xs space-y-3">
          <div>
            <h2 className="text-sm font-semibold text-[var(--cc-text)] flex items-center gap-1.5">
              <span>🔐</span> Commercial Single Sign-On (SSO)
            </h2>
            <p className="text-xs text-[var(--cc-text-muted)] mt-1">
              Sign in with your Customs House Agent (CHA) work email (e.g. <code>broker@customs.com</code> or <code>ops@dhl.com</code>) to access or create corporate bundles.
            </p>
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const form = e.currentTarget;
              const input = form.elements.namedItem("landingEmail") as HTMLInputElement;
              const email = input?.value?.trim().toLowerCase();
              if (email) {
                document.cookie = `cargoclear_session_token=mock-jwt-${email}-LICENSED_CHA; path=/; max-age=86400; SameSite=Lax`;
                window.location.reload();
              }
            }}
            className="flex flex-col sm:flex-row gap-2"
          >
            <input
              name="landingEmail"
              type="email"
              required
              placeholder="agent@customs.com"
              className="flex-1 rounded border border-[var(--cc-border-strong)] bg-[var(--cc-surface)] px-3 py-1.5 text-xs text-[var(--cc-text)] focus:outline-hidden focus:ring-1 focus:ring-[var(--cc-focus)]"
            />
            <button
              type="submit"
              className="rounded bg-[var(--cc-focus)] px-4 py-1.5 text-xs font-semibold text-white hover:opacity-90 cursor-pointer whitespace-nowrap"
            >
              Sign In with Corporate SSO
            </button>
          </form>
          <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t border-[var(--cc-border)]">
            <span className="text-[10px] text-[var(--cc-text-muted)]">Quick presets:</span>
            <button
              type="button"
              onClick={() => {
                document.cookie = `cargoclear_session_token=mock-jwt-demo-cha@customs.com-LICENSED_CHA; path=/; max-age=86400; SameSite=Lax`;
                window.location.reload();
              }}
              className="text-[10px] rounded bg-[var(--cc-surface)] border border-[var(--cc-border)] px-2 py-0.5 text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] cursor-pointer"
            >
              customs.com
            </button>
            <button
              type="button"
              onClick={() => {
                document.cookie = `cargoclear_session_token=mock-jwt-agent@dhl.com-LICENSED_CHA; path=/; max-age=86400; SameSite=Lax`;
                window.location.reload();
              }}
              className="text-[10px] rounded bg-[var(--cc-surface)] border border-[var(--cc-border)] px-2 py-0.5 text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] cursor-pointer"
            >
              dhl.com
            </button>
            <button
              type="button"
              onClick={() => {
                document.cookie = `cargoclear_session_token=mock-jwt-broker@fedex.com-LICENSED_CHA; path=/; max-age=86400; SameSite=Lax`;
                window.location.reload();
              }}
              className="text-[10px] rounded bg-[var(--cc-surface)] border border-[var(--cc-border)] px-2 py-0.5 text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] cursor-pointer"
            >
              fedex.com
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
              document.cookie = `cargoclear_session_token=; path=/; max-age=0; SameSite=Lax`;
              window.location.reload();
            }}
            className="text-[11px] text-[var(--cc-text-muted)] hover:text-[var(--cc-text)] underline cursor-pointer"
          >
            Sign out
          </button>
        </div>
      )}

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          disabled={pending !== null}
          onClick={() => start("empty", () => api.createBundle())}
          className="rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] px-4 py-2 text-sm font-semibold text-[var(--cc-text)] hover:bg-[var(--cc-surface-2)] disabled:opacity-50 cursor-pointer"
        >
          {pending === "empty" ? "Creating bundle..." : "New empty bundle"}
        </button>

        {showDemo && (
          <button
            type="button"
            disabled={pending !== null}
            onClick={() => start("demo", () => api.createCaseCDemo())}
            className="rounded-[var(--cc-radius)] bg-[var(--cc-focus)] px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50 cursor-pointer"
          >
            {pending === "demo" ? "Starting demo..." : "Start Case C demo"}
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
        <p className="text-[11px] text-[var(--cc-text-muted)] leading-relaxed">
          Demo mode: the Case C demo loads an invoice, bill of lading and packing list for a seamless-pipe
          shipment (HS 7304). Extraction uses synthetic fixtures keyed on filename, not a real document
          reading.
        </p>
      )}
    </main>
  );
}

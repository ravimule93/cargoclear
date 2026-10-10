"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { toErrorEnvelope } from "@/lib/errors";
import { useMeta } from "@/lib/hooks/useMeta";
import type { Bundle } from "@/lib/types";

type Pending = "empty" | "demo" | null;

export default function Home() {
  const router = useRouter();
  const { meta, loading: metaLoading, error: metaError, retry: retryMeta } = useMeta();
  const [pending, setPending] = useState<Pending>(null);
  const [error, setError] = useState<string | null>(null);

  const start = async (kind: Exclude<Pending, null>, create: () => Promise<Bundle>) => {
    setPending(kind);
    setError(null);
    try {
      const bundle = await create();
      router.push(`/workbench/${bundle.id}`);
    } catch (err: unknown) {
      setError(toErrorEnvelope(err).message);
      setPending(null);
    }
  };

  const showDemo = meta?.app_mode === "demo";

  return (
    <main className="mx-auto flex min-h-dvh max-w-xl flex-col justify-center gap-6 p-6">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-tight text-[var(--cc-text)]">CargoClear-JAPAC</h1>
        <p className="text-sm text-[var(--cc-text-muted)] leading-relaxed">
          Pre-submission adversarial customs adjudicator. Create a bundle, add trade documents and run
          the analysis. Decision support only: the authorised CHA decides.
        </p>
      </header>

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

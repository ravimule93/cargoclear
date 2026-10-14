"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { toErrorEnvelope } from "@/lib/errors";
import { useMeta } from "@/lib/hooks/useMeta";
import { ModeBadge } from "@/components/shell/ModeBadge";
import type { Bundle } from "@/lib/types";

type Pending = "empty" | "demo" | "demo-d" | null;

/** The destinations the rules cover: the checks and the duty estimate depend on where the goods are going. */
const DESTINATIONS = [
  { code: "SG", label: "Singapore (SG)" },
  { code: "IN", label: "India (IN)" },
] as const;
type Destination = (typeof DESTINATIONS)[number]["code"];

export default function Home() {
  const router = useRouter();
  const { meta, loading: metaLoading, error: metaError, retry: retryMeta } = useMeta();
  const [pending, setPending] = useState<Pending>(null);
  const [error, setError] = useState<string | null>(null);
  const [destination, setDestination] = useState<Destination>("SG");

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
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold tracking-tight text-[var(--cc-text)]">CargoClear-JAPAC</h1>
          <ModeBadge />
        </div>
        <p className="text-sm text-[var(--cc-text-muted)] leading-relaxed">
          Pre-submission customs document assessment. Create a bundle, add trade documents and run
          the analysis. Decision support only: the authorised CHA decides.
        </p>
      </header>

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

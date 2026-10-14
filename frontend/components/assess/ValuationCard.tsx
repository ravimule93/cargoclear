import type { ValuationEstimate } from "@/lib/types";

interface ValuationCardProps {
  valuation: ValuationEstimate;
}

/** "INR 5,443,559.38" in the number style of the currency's home market; a plain number + code if the code is unknown. */
export function formatMoney(value: number | null | undefined, currency?: string | null): string {
  if (value === null || value === undefined) return "n/a";
  try {
    return new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en-US", {
      style: "currency",
      currency: currency || "USD",
      currencyDisplay: "code",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${value.toFixed(2)}${currency ? ` ${currency}` : ""}`;
  }
}

/** "730451" -> "7304.51", "73043100" -> "7304.31.00": how a tariff code is written; anything else is shown as given. */
export function formatHs(code: string | null | undefined): string {
  const digits = (code ?? "").replace(/\D/g, "");
  if (digits.length === 6) return `${digits.slice(0, 4)}.${digits.slice(4)}`;
  if (digits.length === 8) return `${digits.slice(0, 4)}.${digits.slice(4, 6)}.${digits.slice(6)}`;
  return code ?? "";
}

function Row({ label, value, strong = false, testId }: { label: string; value: string; strong?: boolean; testId?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className={strong ? "font-semibold text-[var(--cc-text)]" : "text-[var(--cc-text-muted)]"}>{label}</dt>
      <dd data-testid={testId} className={`font-mono tabular-nums ${strong ? "font-bold text-[var(--cc-text)]" : "text-[var(--cc-text)]"}`}>
        {value}
      </dd>
    </div>
  );
}

/**
 * Indicative assessable value and duty exposure. It is information for the authorised agent, never the status and never an
 * amount payable: the card says so, lists every assumption the estimate made, and names the rule set it used.
 */
export function ValuationCard({ valuation: v }: ValuationCardProps) {
  const invoiceCur = v.invoice_currency ?? "";
  const destCur = v.destination_currency ?? "";

  return (
    <section
      aria-labelledby="valuation-heading"
      data-testid="valuation-card"
      className="flex flex-col gap-2 rounded-[var(--cc-radius)] border border-[var(--cc-border)] bg-[var(--cc-surface-2)] p-3 text-xs"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 id="valuation-heading" className="text-xs font-bold uppercase text-[var(--cc-text-subtle)]">
          Indicative duty exposure ({v.destination_country}{v.hs_code ? `, HS ${formatHs(v.hs_code)}` : ""})
        </h3>
        <span
          data-testid="valuation-status"
          className="rounded border border-[var(--cc-border-strong)] px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--cc-text-muted)]"
        >
          {v.status === "ESTIMATED" ? "Estimate" : v.status === "PARTIAL" ? "Partial estimate" : "Not available"}
        </span>
      </div>

      <p className="text-[11px] leading-relaxed text-[var(--cc-text-muted)]">{v.disclaimer}</p>

      {v.reason && (
        <p role="note" className="text-[11px] font-medium leading-relaxed text-[var(--cc-warn)]">
          {v.status === "NOT_AVAILABLE" ? "No estimate: " : "Incomplete: "}
          {v.reason}
        </p>
      )}

      {v.transaction_value !== null && v.transaction_value !== undefined && (
        <dl className="flex flex-col gap-1">
          <Row label={`Transaction value${v.incoterm ? ` (${v.incoterm})` : ""}`} value={formatMoney(v.transaction_value, invoiceCur)} />
          {v.freight !== null && v.freight !== undefined && <Row label="+ Freight" value={formatMoney(v.freight, invoiceCur)} />}
          {v.insurance !== null && v.insurance !== undefined && <Row label="+ Insurance" value={formatMoney(v.insurance, invoiceCur)} />}
          {v.assessable_value !== null && v.assessable_value !== undefined && (
            <>
              <Row
                label={`Assessable value (CIF) at ${v.exchange_rate ?? "?"} ${invoiceCur}/${destCur}`}
                value={formatMoney(v.assessable_value, destCur)}
                strong
                testId="valuation-assessable"
              />
            </>
          )}
        </dl>
      )}

      {v.duties.length > 0 && (
        <div className="flex flex-col">
          <ul aria-label={`Duty lines in ${destCur}`} className="flex flex-col">
            {v.duties.map((line) => (
              <li key={line.name} className="flex flex-col gap-0.5 border-t border-[var(--cc-border)] py-1.5">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-semibold text-[var(--cc-text)]">{line.name}</span>
                  <span className="font-mono tabular-nums text-[var(--cc-text)]">{formatMoney(line.amount, destCur)}</span>
                </div>
                <span className="text-[10px] leading-snug text-[var(--cc-text-muted)]">
                  {line.rate_pct !== null && line.rate_pct !== undefined ? `${line.rate_pct}%` : "rate n/a"}
                  {line.base !== null && line.base !== undefined ? ` of ${formatMoney(line.base, destCur)}` : ""}
                  {line.note ? ` · ${line.note}` : ""}
                </span>
              </li>
            ))}
          </ul>
          <div className="flex items-baseline justify-between gap-3 border-t-2 border-[var(--cc-border-strong)] pt-1.5">
            <span className="font-bold text-[var(--cc-text)]">Indicative total</span>
            <span data-testid="valuation-total" className="font-mono font-bold tabular-nums text-[var(--cc-text)]">
              {formatMoney(v.total_duty, destCur)}
            </span>
          </div>
        </div>
      )}

      {v.implied_hs_code && v.implied_total_duty !== null && v.implied_total_duty !== undefined && (
        <p data-testid="valuation-implied" className="text-[11px] leading-relaxed text-[var(--cc-text-muted)]">
          If the goods are classified under the subheading the certificate&apos;s chemistry points to ({formatHs(v.implied_hs_code)}),
          the estimate{" "}
          {Math.abs(v.implied_total_duty - (v.total_duty ?? 0)) < 0.005 ? (
            <>is <span className="font-semibold text-[var(--cc-text)]">unchanged</span>: the reference data gives both subheadings the same rates.</>
          ) : (
            <>
              becomes{" "}
              <span className="font-mono font-semibold text-[var(--cc-text)]">{formatMoney(v.implied_total_duty, destCur)}</span>.
            </>
          )}
        </p>
      )}

      {v.assumptions.length > 0 && (
        <details className="text-[11px] text-[var(--cc-text-muted)]" data-testid="valuation-assumptions">
          <summary className="cursor-pointer font-semibold text-[var(--cc-text)]">
            What this estimate assumed ({v.assumptions.length})
          </summary>
          <ul className="mt-1 list-disc pl-4 leading-relaxed">
            {v.assumptions.map((assumption, i) => (
              <li key={`${i}:${assumption}`}>{assumption}</li>
            ))}
          </ul>
        </details>
      )}

      {v.rule_set && (
        <p className="text-[10px] leading-relaxed text-[var(--cc-text-subtle)]">
          Rule set: <span className="font-mono font-semibold">{v.rule_set}</span>
          {v.regulation_ref ? ` — ${v.regulation_ref}` : ""}
        </p>
      )}
    </section>
  );
}

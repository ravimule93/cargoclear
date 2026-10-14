import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { openCaseDDemoWorkbench } from "./support/case-d";

/** The declaration pre-fill pack, downloaded through the same proxy the browser uses for everything else. */
test.describe("Declaration pre-fill", () => {
  test("a bundle that is not cleared gives a pack that says so, as JSON and as a PDF", async ({ page }) => {
    await openCaseDDemoWorkbench(page);
    await page.getByTestId("run-button").click();
    await expect(page.getByTestId("status-pill")).toContainText("Material Contradiction", { timeout: 30_000 });

    const card = page.getByTestId("prefill-card");
    await expect(card).toBeVisible();
    await expect(card.getByTestId("prefill-caveat")).toContainText("Not cleared");

    const jsonHref = await card.getByTestId("prefill-json").getAttribute("href");
    const pdfHref = await card.getByTestId("prefill-pdf").getAttribute("href");
    expect(jsonHref).toMatch(/^\/api\/proxy\/bundles\/bnd-[A-Za-z0-9_-]+\/prefill\?iteration=1&download=true$/);
    expect(pdfHref).toMatch(/^\/api\/proxy\/bundles\/bnd-[A-Za-z0-9_-]+\/prefill\.pdf\?iteration=1$/);

    const json = await page.request.get(jsonHref!);
    expect(json.status()).toBe(200);
    expect(json.headers()["content-disposition"]).toMatch(/^attachment; filename="cargoclear-prefill-bnd-[A-Za-z0-9_-]+-assessment1\.json"$/);
    const pack = await json.json();
    expect(pack.schema_id).toBe("cargoclear.declaration-prefill");
    expect(pack.banner).toMatch(/^NOT CLEARED\./);
    expect(pack.parties.consignee.value).toBe("MUMBAI INFRA PIPING PVT LTD");
    expect(pack.lines[0].hs_code.review.join(" ")).toContain("M-001");
    expect(pack.to_be_supplied.map((i: { id: string }) => i.id)).toContain("IEC");

    const pdf = await page.request.get(pdfHref!);
    expect(pdf.status()).toBe(200);
    expect(pdf.headers()["content-type"]).toBe("application/pdf");
    const bytes = await pdf.body();
    expect(bytes.subarray(0, 5).toString()).toBe("%PDF-");
    expect(bytes.length).toBeGreaterThan(5_000);
  });
});

test.describe("Audit signature", () => {
  test("a completed assessment has its audit head signed, and the badge says with what and what that means", async ({ page }) => {
    await openCaseDDemoWorkbench(page);
    await page.getByTestId("run-button").click();
    await expect(page.getByTestId("status-pill")).toContainText("Material Contradiction", { timeout: 30_000 });

    await page.locator("#tab-audit").click();
    await expect(page.getByTestId("audit-verified-badge")).toHaveText("Chain verified");
    const badge = page.getByTestId("audit-signature-badge");
    await expect(badge).toHaveAttribute("data-status", "SIGNED");
    await expect(badge).toContainText("Head signed through #");
    await expect(badge).toContainText("demo key, not KMS"); // the demo signs with a throwaway key and says so
    await expect(page.getByTestId("audit-sign-now")).toHaveCount(0); // nothing unsigned
    await expect(page.getByLabel("Reasoning delta and audit trail")).toContainText("AUDIT_HEAD_SIGNED");

    await page.getByText("What a signature means here").click();
    await expect(page.getByLabel("Reasoning delta and audit trail")).toContainText("Not legal non-repudiation");

    await page.addStyleTag({ content: "*, *::before, *::after { transition: none !important; animation: none !important; }" });
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    const serious = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
    expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
  });
});

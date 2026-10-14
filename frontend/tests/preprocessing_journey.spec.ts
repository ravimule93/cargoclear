import { test, expect } from "@playwright/test";
import { openCaseDDemoWorkbench } from "./support/case-d";

/** The page images the model was shown are kept, and the viewer links to them: "what did it see?" is answerable. */
test.describe("Processed pages", () => {
  test("the viewer links to the page image the model was shown, and it is a real PNG", async ({ page }) => {
    await openCaseDDemoWorkbench(page);
    await page.getByTestId("run-button").click();
    await expect(page.getByTestId("status-pill")).toContainText("Material Contradiction", { timeout: 30_000 });

    const link = page.getByTestId("model-view-link");
    await expect(link).toBeVisible();
    await expect(link).toHaveText("What the model saw");
    const href = await link.getAttribute("href");
    expect(href).toMatch(/^\/api\/proxy\/bundles\/bnd-[A-Za-z0-9_-]+\/documents\/doc-[0-9a-f]+\/pages\/1\?iteration=1$/); // the page of THE assessment on screen

    const response = await page.request.get(href!);
    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toBe("image/png");
    const bytes = await response.body();
    expect(bytes.subarray(1, 4).toString()).toBe("PNG");
    expect(bytes.length).toBeGreaterThan(1_000);

    // an unrelated document id is a 404, not somebody else's page
    const other = await page.request.get(href!.replace(/doc-[0-9a-f]+/, "doc-0123456789abcdef"));
    expect(other.status()).toBe(404);
    // an assessment that does not exist has no pages
    expect((await page.request.get(href!.replace("iteration=1", "iteration=9"))).status()).toBe(404);
  });
});

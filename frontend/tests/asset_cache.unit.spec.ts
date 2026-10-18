import { expect, test } from "@playwright/test";
import { createNextConfig } from "../next.config";

for (const mode of ["development", "production"] as const) {
  test(`${mode} serves the appropriate asset cache policy`, async () => {
    const nextConfig = createNextConfig(mode);
    const rules = await nextConfig.headers!();
    const staticRule = rules.find((rule) => rule.source === "/_next/static/:path*");
    const cacheControl = staticRule?.headers.find((header) => header.key === "Cache-Control");

    expect(cacheControl?.value).toBe(mode === "production"
      ? "public, max-age=31536000, immutable"
      : "no-store, no-cache, must-revalidate, max-age=0");

    // A fresh local asset URL recovers even browsers retaining old immutable CSS.
    expect(nextConfig.assetPrefix).toBe(mode === "development" ? "/_cc-dev-assets" : undefined);
    // Recovery must not erase sign-in cookies, theme storage, or app data.
    expect(rules.flatMap((rule) => rule.headers).some((header) => header.key === "Clear-Site-Data")).toBe(false);

    expect(rules.find((rule) => rule.source === "/((?!_next/static|_next/image|favicon.ico).*)")?.headers)
      .toContainEqual({ key: "Cache-Control", value: "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0, s-maxage=0" });
  });
}

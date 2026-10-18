import { expect, test } from "@playwright/test";

import { DEMO_ACCOUNTS, demoSignIn, demoToken, demoUserFromCookie } from "../lib/session";

test.describe("demo session helpers", () => {
  test("round-trips the demo account from either proxy cookie", () => {
    expect(demoToken(" Demo-CHA@Customs.com ")).toBe("mock-jwt-demo-cha@customs.com-LICENSED_CHA");
    for (const name of ["__session", "cargoclear_session_token"]) {
      expect(demoUserFromCookie(`${name}=${demoToken("agent@dhl.com")}`)).toMatchObject({
        email: "agent@dhl.com", tenant_id: "dhl.com", role: "LICENSED_CHA",
      });
    }
  });

  test("demo session sign-in is unavailable outside a browser", () => {
    expect(demoSignIn("demo-cha@customs.com", "demo")).toBe(false);
  });

  test("allows browser demo sign-in in any mode and writes both session cookies", () => {
    const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
    const previousDocument = Object.getOwnPropertyDescriptor(globalThis, "document");
    const cookies: string[] = [];
    Object.defineProperty(globalThis, "window", { configurable: true, value: { location: { protocol: "https:" } } });
    Object.defineProperty(globalThis, "document", {
      configurable: true,
      value: { set cookie(value: string) { cookies.push(value); } },
    });
    try {
      for (const mode of ["live", "demo", undefined] as const) {
        cookies.length = 0;
        expect(demoSignIn("demo-cha@customs.com", mode)).toBe(true);
        expect(cookies).toEqual([
          "__session=mock-jwt-demo-cha@customs.com-LICENSED_CHA; path=/; max-age=86400; SameSite=Lax; Secure",
          "cargoclear_session_token=mock-jwt-demo-cha@customs.com-LICENSED_CHA; path=/; max-age=86400; SameSite=Lax; Secure",
        ]);
      }
    } finally {
      if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
      else Reflect.deleteProperty(globalThis, "window");
      if (previousDocument) Object.defineProperty(globalThis, "document", previousDocument);
      else Reflect.deleteProperty(globalThis, "document");
    }
  });

  test("keeps the three established demo identities", () => {
    expect(DEMO_ACCOUNTS.map((account) => account.email)).toEqual([
      "demo-cha@customs.com", "agent@dhl.com", "broker@fedex.com",
    ]);
  });
});

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

  test("allows demo session sign-in for preset accounts in any mode", () => {
    expect(demoSignIn("demo-cha@customs.com", "live")).toBe(true);
    expect(demoSignIn("demo-cha@customs.com", "demo")).toBe(true);
    expect(demoSignIn("demo-cha@customs.com", undefined)).toBe(true);
  });

  test("keeps the three established demo identities", () => {
    expect(DEMO_ACCOUNTS.map((account) => account.email)).toEqual([
      "demo-cha@customs.com", "agent@dhl.com", "broker@fedex.com",
    ]);
  });
});

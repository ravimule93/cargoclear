import { expect, test } from "@playwright/test";
import { api } from "../lib/api";

const originalFetch = globalThis.fetch;
const authenticationMessage = "Authentication required. Please sign in to continue.";

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("protected bundle creation normalizes a JSON 401 while preserving error context", async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({
    code: "AUTHENTICATION_ERROR",
    message: "A verified end-user session is required.",
    detail: { reason: "expired_session" },
    request_id: "request-auth-required",
  }), { status: 401, headers: { "Content-Type": "application/json" } });

  await expect(api.createBundle("Authentication regression", "SG")).rejects.toEqual({
    code: "AUTHENTICATION_ERROR",
    message: authenticationMessage,
    detail: { reason: "expired_session" },
    request_id: "request-auth-required",
  });
});

test("protected bundle creation gives the same sign-in guidance for a non-JSON 401", async () => {
  globalThis.fetch = async () => new Response("<html>Unauthorized</html>", {
    status: 401,
    statusText: "Unauthorized",
    headers: { "Content-Type": "text/html" },
  });

  await expect(api.createBundle()).rejects.toEqual({
    code: "HTTP_401",
    message: authenticationMessage,
    detail: null,
  });
});

test("a 403 permission failure retains its distinct explanation and context", async () => {
  const forbidden = {
    code: "FORBIDDEN",
    message: "This workspace is not available to your organization.",
    detail: { tenant_id: "restricted.example" },
    request_id: "request-forbidden",
  };
  globalThis.fetch = async () => new Response(JSON.stringify(forbidden), {
    status: 403,
    headers: { "Content-Type": "application/json" },
  });

  await expect(api.createBundle()).rejects.toEqual(forbidden);
});

test("a sign-in 401 retains credential feedback instead of requesting sign-in again", async () => {
  const invalidCredentials = {
    code: "AUTHENTICATION_ERROR",
    message: "Invalid password. Please check your credentials.",
    detail: { field: "password" },
    request_id: "request-invalid-credentials",
  };
  globalThis.fetch = async () => new Response(JSON.stringify(invalidCredentials), {
    status: 401,
    headers: { "Content-Type": "application/json" },
  });

  await expect(api.signIn({ email: "review@example.com", password: "incorrect-password" })).rejects.toEqual(invalidCredentials);
});

test("the protected user-audit endpoint still normalizes 401 under the auth route prefix", async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({
    code: "AUTHENTICATION_ERROR",
    message: "A verified end-user session is required.",
    detail: null,
    request_id: "request-user-audit",
  }), { status: 401, headers: { "Content-Type": "application/json" } });

  await expect(api.getUserAudit()).rejects.toEqual({
    code: "AUTHENTICATION_ERROR",
    message: authenticationMessage,
    detail: null,
    request_id: "request-user-audit",
  });
});

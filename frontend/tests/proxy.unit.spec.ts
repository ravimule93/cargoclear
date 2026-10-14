import { expect, test } from "@playwright/test";
import {
  CLIENT_IP_HEADER,
  IdTokenSource,
  UpstreamAuthError,
  authMode,
  backendBase,
  buildTargetUrl,
  clientIpFrom,
  downstreamResponseHeaders,
  isStreamPath,
  requestIdFor,
  trustedProxyHops,
  upstreamRequestHeaders,
} from "../lib/server/proxy";

const BASE = "https://cargoclear-api-abc123-el.a.run.app";

function jwt(expSeconds: number): string {
  const part = (value: object) => Buffer.from(JSON.stringify(value)).toString("base64url");
  return `${part({ alg: "RS256" })}.${part({ exp: expSeconds })}.signature`;
}

test.describe("buildTargetUrl", () => {
  test("maps /api/proxy/<path> below /api/v1 and keeps the query string", () => {
    const url = buildTargetUrl(BASE, ["bundles", "bnd-1", "documents"], "?x=1");
    expect(url?.toString()).toBe(`${BASE}/api/v1/bundles/bnd-1/documents?x=1`);
  });

  test("keeps the API_BASE host and ignores a path on it", () => {
    expect(buildTargetUrl("http://localhost:8080/ignored", ["meta"])?.toString()).toBe(
      "http://localhost:8080/api/v1/meta"
    );
  });

  for (const segments of [
    [],
    [".."],
    ["bundles", ".."],
    ["."],
    [""],
    ["..%2F..%2Fhealthz"],
    ["%2e%2e", "healthz"],
    ["bundles%2F..%2F..%2Fhealthz"],
    ["a\\b"],
    ["a%00b"],
    ["%E0%A4%A"], // malformed percent-encoding
  ]) {
    test(`rejects ${JSON.stringify(segments)}`, () => {
      expect(buildTargetUrl(BASE, segments)).toBeNull();
    });
  }
});

test.describe("isStreamPath", () => {
  test("only the stream endpoint has no deadline", () => {
    expect(isStreamPath(["bundles", "bnd-1", "stream"])).toBe(true);
    expect(isStreamPath(["bundles", "bnd-1", "analyze"])).toBe(false);
    expect(isStreamPath([])).toBe(false);
  });
});

test.describe("clientIpFrom", () => {
  const withXff = (value: string) => new Headers({ "x-forwarded-for": value });

  test("takes the entry Cloud Run appended (the last), never the client-supplied ones", () => {
    expect(clientIpFrom(withXff("6.6.6.6, 203.0.113.9"))).toBe("203.0.113.9");
    expect(clientIpFrom(withXff("203.0.113.9"))).toBe("203.0.113.9");
  });

  test("hops=2 skips the load balancer's own entry", () => {
    expect(clientIpFrom(withXff("6.6.6.6, 203.0.113.9, 35.1.1.1"), 2)).toBe("203.0.113.9");
  });

  test("accepts IPv6 and rejects anything that is not an IP", () => {
    expect(clientIpFrom(withXff("2001:db8::1"))).toBe("2001:db8::1");
    expect(clientIpFrom(withXff("not-an-ip"))).toBeNull();
    expect(clientIpFrom(new Headers())).toBeNull();
    expect(clientIpFrom(withXff("1.2.3.4"), 5)).toBeNull();
  });
});

test.describe("trustedProxyHops / authMode / backendBase", () => {
  test("parse the environment defensively", () => {
    expect(trustedProxyHops({})).toBe(1);
    expect(trustedProxyHops({ TRUSTED_PROXY_HOPS: "2" })).toBe(2);
    expect(trustedProxyHops({ TRUSTED_PROXY_HOPS: "0" })).toBe(1);
    expect(trustedProxyHops({ TRUSTED_PROXY_HOPS: "abc" })).toBe(1);
    expect(authMode({})).toBe("none");
    expect(authMode({ API_AUTH_MODE: "google-id-token" })).toBe("google-id-token");
    expect(authMode({ API_AUTH_MODE: "anything-else" })).toBe("none");
    expect(backendBase({})).toBe("http://localhost:8080");
    expect(backendBase({ API_BASE: BASE })).toBe(BASE);
  });
});

test.describe("upstreamRequestHeaders", () => {
  const browser = new Headers({
    "content-type": "application/json",
    "content-length": "12",
    accept: "text/event-stream",
    "last-event-id": "7",
    cookie: "session=secret",
    authorization: "Bearer from-the-browser",
    host: "evil.example",
    [CLIENT_IP_HEADER]: "6.6.6.6",
    "x-forwarded-for": "6.6.6.6",
  });

  test("forwards only the allowlist; cookies, authorization and a spoofed client IP never pass", () => {
    const headers = upstreamRequestHeaders(browser, { idToken: null, clientIp: null, requestId: "req-1" });
    expect(Object.fromEntries(headers)).toEqual({
      "content-type": "application/json",
      "content-length": "12",
      accept: "text/event-stream",
      "last-event-id": "7",
      "x-request-id": "req-1",
    });
  });

  test("adds the observed client IP and the service's own bearer token", () => {
    const headers = upstreamRequestHeaders(browser, {
      idToken: "id.token.value",
      clientIp: "203.0.113.9",
      requestId: "req-2",
    });
    expect(headers.get(CLIENT_IP_HEADER)).toBe("203.0.113.9");
    expect(headers.get("authorization")).toBe("Bearer id.token.value");
    expect(headers.get("cookie")).toBeNull();
  });
});

test.describe("requestIdFor", () => {
  test("keeps a well-formed id and replaces anything else", () => {
    expect(requestIdFor(new Headers({ "x-request-id": "abc-123_X.y" }))).toBe("abc-123_X.y");
    expect(requestIdFor(new Headers({ "x-request-id": "bad id!" }), () => "generated")).toBe("generated");
    expect(requestIdFor(new Headers({ "x-request-id": "x".repeat(65) }), () => "generated")).toBe("generated");
    expect(requestIdFor(new Headers(), () => "generated")).toBe("generated");
  });
});

test.describe("downstreamResponseHeaders", () => {
  test("drops the headers that describe a body this server re-streams", () => {
    const out = downstreamResponseHeaders(
      new Headers({
        "content-type": "application/pdf",
        "content-length": "10",
        "content-encoding": "gzip",
        "transfer-encoding": "chunked",
        "set-cookie": "a=b",
        "x-request-id": "r",
        "cache-control": "no-store",
      })
    );
    expect(Object.fromEntries(out)).toEqual({
      "content-type": "application/pdf",
      "x-request-id": "r",
      "cache-control": "no-store",
    });
  });
});

test.describe("IdTokenSource", () => {
  const NOW = 1_700_000_000_000;

  function source(responses: Array<() => Response | Promise<Response>>, now: () => number = () => NOW) {
    const calls: Array<{ url: string; headers: Record<string, string> }> = [];
    const fetchImpl = (async (url: string, init?: RequestInit) => {
      calls.push({ url, headers: init?.headers as Record<string, string> });
      const next = responses.shift();
      if (!next) throw new Error("unexpected extra call");
      return next();
    }) as unknown as typeof fetch;
    return { calls, tokens: new IdTokenSource(now, fetchImpl, {}) };
  }

  test("asks the metadata server for the API's audience and caches the token", async () => {
    const token = jwt(NOW / 1000 + 3600);
    const { calls, tokens } = source([() => new Response(token)]);

    expect(await tokens.get(BASE)).toBe(token);
    expect(await tokens.get(BASE)).toBe(token); // cached: the second call would throw "unexpected extra call"

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(
      `http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience=${encodeURIComponent(BASE)}`
    );
    expect(calls[0].headers["Metadata-Flavor"]).toBe("Google");
  });

  test("replaces the token 5 minutes before it expires", async () => {
    let now = NOW;
    const first = jwt(NOW / 1000 + 3600);
    const second = jwt(NOW / 1000 + 7200);
    const { tokens } = source([() => new Response(first), () => new Response(second)], () => now);

    expect(await tokens.get(BASE)).toBe(first);
    now = NOW + (3600 - 301) * 1000;
    expect(await tokens.get(BASE)).toBe(first); // still more than 5 minutes left
    now = NOW + (3600 - 299) * 1000;
    expect(await tokens.get(BASE)).toBe(second);
  });

  test("concurrent callers share one metadata request", async () => {
    const token = jwt(NOW / 1000 + 3600);
    const { calls, tokens } = source([async () => new Response(token)]);
    const results = await Promise.all([tokens.get(BASE), tokens.get(BASE), tokens.get(BASE)]);
    expect(results).toEqual([token, token, token]);
    expect(calls).toHaveLength(1);
  });

  test("a token whose expiry cannot be read is still used, with a default lifetime", async () => {
    const opaque = "a.b.c";
    const { tokens } = source([() => new Response(opaque)]);
    expect(await tokens.get(BASE)).toBe(opaque);
  });

  test("a metadata failure is an UpstreamAuthError and is not cached", async () => {
    const token = jwt(NOW / 1000 + 3600);
    const { tokens } = source([() => new Response("nope", { status: 500 }), () => new Response(token)]);

    await expect(tokens.get(BASE)).rejects.toBeInstanceOf(UpstreamAuthError);
    expect(await tokens.get(BASE)).toBe(token); // the failure did not poison the next call
  });

  test("a response that is not a JWT is refused", async () => {
    const { tokens } = source([() => new Response("<html>not a token</html>")]);
    await expect(tokens.get(BASE)).rejects.toBeInstanceOf(UpstreamAuthError);
  });

  test("GCE_METADATA_HOST overrides the host (local stub servers)", async () => {
    const urls: string[] = [];
    const fetchImpl = (async (url: string) => {
      urls.push(url);
      return new Response(jwt(NOW / 1000 + 3600));
    }) as unknown as typeof fetch;
    await new IdTokenSource(() => NOW, fetchImpl, { GCE_METADATA_HOST: "127.0.0.1:9999" }).get(BASE);
    expect(urls[0].startsWith("http://127.0.0.1:9999/computeMetadata/v1/")).toBe(true);
  });
});

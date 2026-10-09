import {
  Bundle,
  CreateBundleBody,
  DocumentRecord,
  RunResponse,
  AssessmentIteration,
  ApiError,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8080";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/proxy${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new ApiError(
      err.code ?? "UNKNOWN",
      err.message ?? res.statusText,
      err.request_id
    );
  }

  return res.json() as Promise<T>;
}

export const api = {
  createBundle: (body: CreateBundleBody) =>
    call<Bundle>("/bundles", { method: "POST", body: JSON.stringify(body) }),

  getBundle: (bundleId: string) => call<Bundle>(`/bundles/${bundleId}`),

  uploadDocument: async (bundleId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`/api/proxy/bundles/${bundleId}/documents`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new ApiError(
        err.code ?? "UNKNOWN",
        err.message ?? res.statusText,
        err.request_id
      );
    }
    return res.json() as Promise<DocumentRecord>;
  },

  analyze: (bundleId: string) =>
    call<RunResponse>(`/bundles/${bundleId}/analyze`, { method: "POST" }),

  reassess: (bundleId: string) =>
    call<RunResponse>(`/bundles/${bundleId}/reassess`, { method: "POST" }),

  assessment: (bundleId: string) =>
    call<AssessmentIteration>(`/bundles/${bundleId}/assessment`),

  iterations: (bundleId: string) =>
    call<AssessmentIteration[]>(`/bundles/${bundleId}/iterations`),
};

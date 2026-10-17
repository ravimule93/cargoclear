import {
  Bundle,
  DocumentDeleted,
  DocumentRecord,
  AssessmentIteration,
  AuditResponse,
  AuditSignature,
  CorrectionRecord,
  CorrectionRequest,
  CorrectionsResponse,
  ErrorEnvelope,
  Meta,
  RunResponse,
  TransformMetadataResponse,
  CheckUserResponse,
  AuthResponse,
  SignUpRequest,
  SignInRequest,
  UserAuditResponse,
  AppMode,
  ExecutionModeStatus,
} from "./types";
import type { ExtractedDoc } from "./corrections";

/** Browser calls go through the Next route handler, which forwards to the FastAPI backend. */
const PROXY_PREFIX = "/api/proxy";

/** Name the backend/pipeline expects for the sample Mill Test Certificate (filename-keyed fixtures). */
export const SAMPLE_MTC_FILENAME = "mtc_pipe_test_cert.pdf";

async function toErrorEnvelope(response: Response): Promise<ErrorEnvelope> {
  try {
    const data = await response.json();
    return {
      code: data.code || `HTTP_${response.status}`,
      message: data.message || response.statusText || "Request failed",
      detail: data.detail ?? null,
      request_id: data.request_id,
    };
  } catch {
    return {
      code: `HTTP_${response.status}`,
      message: response.statusText || "Request failed",
      detail: null,
    };
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${PROXY_PREFIX}${path}`, options);

  if (!response.ok) {
    // Thrown as a plain envelope object (not an Error); callers branch on `code`.
    throw await toErrorEnvelope(response);
  }

  return response.json() as Promise<T>;
}

export const api = {
  async createBundle(
    reference?: string,
    destination_country: string = "SG"
  ): Promise<Bundle> {
    return request<Bundle>("/bundles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reference, destination_country }),
    });
  },

  async getBundle(bundleId: string): Promise<Bundle> {
    return request<Bundle>(`/bundles/${bundleId}`);
  },

  async listBundles(limit: number = 20): Promise<Bundle[]> {
    return request<Bundle[]>(`/bundles?limit=${limit}`);
  },

  /** `declaredType` (optional): what the uploader says the file is. When the model reads another type the assessment warns (T-001). */
  async uploadDocument(bundleId: string, file: File, declaredType?: string | null): Promise<DocumentRecord> {
    const formData = new FormData();
    formData.append("file", file);
    if (declaredType) formData.append("declared_type", declaredType);

    return request<DocumentRecord>(`/bundles/${bundleId}/documents`, {
      method: "POST",
      body: formData,
    });
  },

  /** Take a document out of a bundle (its file, kept model answers and record). 409 while a run is in progress. */
  async deleteDocument(bundleId: string, documentId: string): Promise<DocumentDeleted> {
    return request<DocumentDeleted>(
      `/bundles/${encodeURIComponent(bundleId)}/documents/${encodeURIComponent(documentId)}`,
      { method: "DELETE" }
    );
  },

  async getDocumentTransformMetadata(
    bundleId: string,
    documentId: string
  ): Promise<TransformMetadataResponse> {
    return request<TransformMetadataResponse>(
      `/bundles/${encodeURIComponent(bundleId)}/documents/${encodeURIComponent(documentId)}/transform-metadata`
    );
  },

  async analyze(bundleId: string, mode: string = "full"): Promise<RunResponse> {
    return request<RunResponse>(`/bundles/${bundleId}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
  },

  async reassess(bundleId: string, mode: string = "full"): Promise<RunResponse> {
    return request<RunResponse>(`/bundles/${bundleId}/reassess`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
  },

  /** Re-run the checks on the stored extraction with the agent's corrections applied (no document is read, no model is called). */
  async recompute(bundleId: string): Promise<RunResponse> {
    return request<RunResponse>(`/bundles/${bundleId}/recompute`, { method: "POST" });
  },

  async getCorrections(bundleId: string): Promise<CorrectionsResponse> {
    return request<CorrectionsResponse>(`/bundles/${bundleId}/corrections`);
  },

  async createCorrection(bundleId: string, body: CorrectionRequest): Promise<CorrectionRecord> {
    return request<CorrectionRecord>(`/bundles/${bundleId}/corrections`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  async revertCorrection(bundleId: string, correctionId: string, reason?: string): Promise<CorrectionRecord> {
    return request<CorrectionRecord>(
      `/bundles/${encodeURIComponent(bundleId)}/corrections/${encodeURIComponent(correctionId)}/revert`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: reason ?? null }),
      }
    );
  },

  /** The extraction of an iteration as its checks saw it (corrected fields carry `corrected` and `original_value`). */
  async getExtractions(bundleId: string, iteration?: number): Promise<ExtractedDoc[]> {
    const query = iteration ? `?iteration=${iteration}` : "";
    return request<ExtractedDoc[]>(`/bundles/${bundleId}/extractions${query}`);
  },

  async getAssessment(bundleId: string): Promise<AssessmentIteration> {
    return request<AssessmentIteration>(`/bundles/${bundleId}/assessment`);
  },

  async listIterations(bundleId: string): Promise<AssessmentIteration[]> {
    return request<AssessmentIteration[]>(`/bundles/${bundleId}/iterations`);
  },

  async getAudit(bundleId: string): Promise<AuditResponse> {
    return request<AuditResponse>(`/bundles/${bundleId}/audit`);
  },

  /** Sign the current head of the audit chain now (the run could not, or events came after it). */
  async signAuditHead(bundleId: string): Promise<AuditSignature> {
    return request<AuditSignature>(`/bundles/${bundleId}/audit/sign`, { method: "POST" });
  },

  async createCaseCDemo(): Promise<Bundle> {
    return request<Bundle>("/demo/case-c", {
      method: "POST",
    });
  },

  /** Demo mode only: Case D, an India import whose certificate contradicts the declared HS code (all four documents). */
  async createCaseDDemo(): Promise<Bundle> {
    return request<Bundle>("/demo/case-d", {
      method: "POST",
    });
  },

  /** Demo mode only: the sample MTC as a File named for the pipeline's filename-keyed fixtures. */
  async fetchSampleMtc(): Promise<File> {
    const response = await fetch(`${PROXY_PREFIX}/demo/case-c/mtc`);
    if (!response.ok) {
      throw await toErrorEnvelope(response);
    }
    const blob = await response.blob();
    return new File([blob], SAMPLE_MTC_FILENAME, { type: "application/pdf" });
  },

  /**
   * Where the declaration pre-fill pack of a bundle can be downloaded (JSON, or the printable PDF summary). A plain URL,
   * not a fetch: the browser downloads it through the same proxy as every other call.
   */
  prefillUrl(bundleId: string, format: "json" | "pdf", iteration?: number): string {
    const base = `${PROXY_PREFIX}/bundles/${encodeURIComponent(bundleId)}/prefill`;
    const query = new URLSearchParams();
    if (iteration) query.set("iteration", String(iteration));
    if (format === "json") query.set("download", "true");
    const qs = query.toString();
    return `${base}${format === "pdf" ? ".pdf" : ""}${qs ? `?${qs}` : ""}`;
  },

  async getMeta(): Promise<Meta> {
    return request<Meta>("/meta");
  },

  async getMode(): Promise<ExecutionModeStatus> {
    return request<ExecutionModeStatus>("/mode");
  },

  async setMode(mode: AppMode): Promise<ExecutionModeStatus> {
    return request<ExecutionModeStatus>("/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
  },

  async checkUser(email: string): Promise<CheckUserResponse> {
    return request<CheckUserResponse>(`/auth/check?email=${encodeURIComponent(email)}`);
  },

  async signUp(data: SignUpRequest): Promise<AuthResponse> {
    return request<AuthResponse>("/auth/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
  },

  async signIn(data: SignInRequest): Promise<AuthResponse> {
    return request<AuthResponse>("/auth/signin", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
  },

  async getUserAudit(): Promise<UserAuditResponse> {
    return request<UserAuditResponse>("/auth/audit");
  },
};

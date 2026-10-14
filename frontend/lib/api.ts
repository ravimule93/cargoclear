import {
  Bundle,
  DocumentRecord,
  AssessmentIteration,
  AuditResponse,
  ErrorEnvelope,
  Meta,
  RunResponse,
  TransformMetadataResponse,
  CheckUserResponse,
  AuthResponse,
  SignUpRequest,
  SignInRequest,
  UserAuditResponse,
} from "./types";

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

  async uploadDocument(bundleId: string, file: File): Promise<DocumentRecord> {
    const formData = new FormData();
    formData.append("file", file);

    return request<DocumentRecord>(`/bundles/${bundleId}/documents`, {
      method: "POST",
      body: formData,
    });
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

  async getAssessment(bundleId: string): Promise<AssessmentIteration> {
    return request<AssessmentIteration>(`/bundles/${bundleId}/assessment`);
  },

  async listIterations(bundleId: string): Promise<AssessmentIteration[]> {
    return request<AssessmentIteration[]>(`/bundles/${bundleId}/iterations`);
  },

  async getAudit(bundleId: string): Promise<AuditResponse> {
    return request<AuditResponse>(`/bundles/${bundleId}/audit`);
  },

  async createCaseCDemo(): Promise<Bundle> {
    return request<Bundle>("/demo/case-c", {
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

  async getMeta(): Promise<Meta> {
    return request<Meta>("/meta");
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

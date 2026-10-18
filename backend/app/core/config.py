"""Application configuration via pydantic-settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application Mode ("demo" or "live")
    app_mode: Literal["demo", "live"] = Field(default="demo", alias="APP_MODE")
    local_storage_path: str = Field(default="./data/storage", alias="LOCAL_STORAGE_PATH")

    # GCP Core
    project_id: str = Field(default="cargoclear-hackathon", alias="PROJECT_ID")
    region: str = Field(default="asia-south1", alias="REGION")

    # Release identity. Deployment supplies these values; ``unknown`` is deliberately
    # conspicuous for local development and must never be used for a release claim.
    release_sha: str = Field(default="unknown", alias="RELEASE_SHA")
    release_timestamp: str = Field(default="unknown", alias="RELEASE_TIMESTAMP")

    # Credentials. Also read from .env (pydantic-settings reads .env into fields, not into os.environ):
    # app.core.mode treats it as present when it is in the process environment OR here, and exports it.
    google_application_credentials: str | None = Field(default=None, alias="GOOGLE_APPLICATION_CREDENTIALS")

    # GCS
    raw_bucket: str = Field(default="cargoclear-raw-pdfs", alias="RAW_BUCKET")

    # Firestore
    firestore_database: str = Field(default="(default)", alias="FIRESTORE_DATABASE")

    # BigQuery
    bq_dataset: str = Field(default="ahtn", alias="BQ_DATASET")
    bq_table_tariff: str = Field(default="master_tariff", alias="BQ_TABLE_TARIFF")
    bq_model_embedding: str = Field(default="embedding_model", alias="BQ_MODEL_EMBEDDING")
    # One tariff lookup is a BigQuery job (embed the description, then VECTOR_SEARCH) that runs in a worker thread:
    # the wait for it is bounded, and at most TARIFF_LOOKUP_CONCURRENCY run at once for one bundle.
    bq_query_timeout_seconds: float = Field(default=30, gt=0, alias="BQ_QUERY_TIMEOUT_SECONDS")
    tariff_lookup_concurrency: int = Field(default=4, ge=1, alias="TARIFF_LOOKUP_CONCURRENCY")

    # Gemini models
    gemini_live_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_LIVE_MODEL")
    gemini_live_location: str = Field(default="asia-south1", alias="GEMINI_LIVE_LOCATION")
    gemini_batch_model: str = Field(default="gemini-2.5-pro", alias="GEMINI_BATCH_MODEL")
    gemini_batch_location: str = Field(default="global", alias="GEMINI_BATCH_LOCATION")

    # Gemini live extraction (agents/extraction.py)
    gemini_timeout_seconds: float = Field(default=120, gt=0, alias="GEMINI_TIMEOUT_SECONDS")
    gemini_max_attempts: int = Field(default=3, ge=1, alias="GEMINI_MAX_ATTEMPTS")
    gemini_max_concurrency: int = Field(default=3, ge=1, alias="GEMINI_MAX_CONCURRENCY")
    gemini_max_output_tokens: int = Field(default=16384, ge=1, alias="GEMINI_MAX_OUTPUT_TOKENS")
    # How much the model may think (agents/extraction.py::thinking_config). Thinking tokens are billed as output and count toward the
    # output cap, and the knob depends on the model: gemini-2.5-flash takes a BUDGET (tokens; 0 switches thinking off, a NEGATIVE value
    # means "do not send the field"); gemini-2.5-pro cannot switch it off (its floor, 128, is used when this is lower); gemini-3.x refuses
    # a budget of ANY value on a request with an image and takes a LEVEL instead (MINIMAL: none; LOW; MEDIUM; HIGH; DEFAULT: do not send
    # the field, the model's own default, which spends a few hundred tokens on a one-word answer). Measured 2026-10-16: docs/input-gating-audit.md.
    gemini_thinking_budget: int = Field(default=0, alias="GEMINI_THINKING_BUDGET")
    gemini_thinking_level: Literal["MINIMAL", "LOW", "MEDIUM", "HIGH", "DEFAULT"] = Field(default="MINIMAL", alias="GEMINI_THINKING_LEVEL")
    # Reuse the model's answer for a document it already read in this bundle: the same pages, model, prompt and settings give the same
    # request, and the request is what costs tokens. Scoped to the bundle, never shared between bundles. false: every run asks again.
    extraction_cache: bool = Field(default=True, alias="EXTRACTION_CACHE")
    # How long a kept answer (the extracted text of a document) is used and kept: each carries an `expires_at` for a Firestore TTL policy
    # (infra/firestore/setup_ttl.sh), and one past it is never used even before Firestore deletes it.
    extraction_cache_ttl_days: int = Field(default=30, ge=1, alias="EXTRACTION_CACHE_TTL_DAYS")
    gemini_max_request_mb: float = Field(default=18, gt=0, alias="GEMINI_MAX_REQUEST_MB")
    gemini_max_pages: int = Field(default=30, ge=1, alias="GEMINI_MAX_PAGES")  # the most page images ONE request may carry (a hard stop)
    # Which pages of a document the model reads (services/relevance.py): page 1 and the pages that look like part of the document,
    # at most MAX_PAGES_SENT of them; the rest are not read and the assessment says so. MAX_PDF_PAGES is how long a FILE may be at upload.
    max_pages_sent: int = Field(default=10, ge=1, alias="MAX_PAGES_SENT")
    max_pdf_pages: int = Field(default=100, ge=1, alias="MAX_PDF_PAGES")
    # Before a file is stored, the first page must be a document the assessment reads: recognised from its text layer, or, when that
    # cannot say (a scan, a language not in the lists), by one small vision request (page 1 at 100 DPI, one word back).
    relevance_gate: bool = Field(default=True, alias="RELEVANCE_GATE")
    # The text layer is the uploader's to write, so a title phrase in it is trusted only when the words that name the document can be SEEN
    # on the rendered first page (not white on white, not a speck). A phrase that IS visible still passes without a model call. true:
    # never accept on the text layer, ask the model about every new file (about 1,900 tokens each) - the strict setting.
    relevance_vision_always: bool = Field(default=False, alias="RELEVANCE_VISION_ALWAYS")

    # Run lifecycle (services/orchestrator.py): a run proves it is alive by touching its run record and extending its lease
    # every RUN_HEARTBEAT_SECONDS, and a run whose lease (or RUNNING record) has been untouched for RUN_STALE_AFTER_SECONDS is dead.
    run_heartbeat_seconds: float = Field(default=10, gt=0, alias="RUN_HEARTBEAT_SECONDS")
    run_stale_after_seconds: float = Field(default=90, gt=0, alias="RUN_STALE_AFTER_SECONDS")
    run_timeout_seconds: float = Field(default=1200, gt=0, alias="RUN_TIMEOUT_SECONDS")
    # Who may run an assessment is a LEASE per bundle (repo/leases.py), so several API instances can share the work.
    # A run that is queued but not picked up by a worker within RUN_QUEUE_WAIT_SECONDS is given up (reaped as interrupted).
    run_queue_wait_seconds: float = Field(default=900, gt=0, alias="RUN_QUEUE_WAIT_SECONDS")
    # How a run reaches a worker. "local": this process runs it as a background task right after the 202 (demo, tests, a
    # single always-on instance). "cloudtasks": the API enqueues a Cloud Task and a worker request executes it, so scale-in
    # cannot kill a run and any instance can take it (services/run_queue.py; docs/GCP_VERIFICATION.md section 9).
    run_dispatch: Literal["local", "cloudtasks"] = Field(default="local", alias="RUN_DISPATCH")
    tasks_queue: str = Field(default="cargoclear-runs", alias="TASKS_QUEUE")
    tasks_location: str | None = Field(default=None, alias="TASKS_LOCATION")  # default: REGION
    # The identity Cloud Tasks signs its OIDC token as: it needs roles/run.invoker on this service, and it is the ONLY
    # caller the internal worker endpoint accepts (INTERNAL_CALLER_EMAIL, default the same).
    tasks_service_account: str | None = Field(default=None, alias="TASKS_SERVICE_ACCOUNT")
    internal_caller_email: str | None = Field(default=None, alias="INTERNAL_CALLER_EMAIL")
    # Public (run.app) URL of THIS service: the task's target and the audience of its OIDC token
    api_url: str | None = Field(default=None, alias="API_URL")
    # How long Cloud Tasks waits for one worker request: must exceed RUN_TIMEOUT_SECONDS (Cloud Tasks allows up to 1800)
    tasks_dispatch_deadline_seconds: float = Field(default=1500, gt=0, le=1800, alias="TASKS_DISPATCH_DEADLINE_SECONDS")

    # SSE stream (api/v1/stream.py): poll fast while a run is active, slowly otherwise
    stream_poll_active_seconds: float = Field(default=1.0, gt=0, alias="STREAM_POLL_ACTIVE_SECONDS")
    stream_poll_idle_seconds: float = Field(default=3.0, gt=0, alias="STREAM_POLL_IDLE_SECONDS")

    # Request and upload limits (gateway/limits.py, api/v1/documents.py, domain/schemas.py::CreateBundleRequest)
    max_upload_mb: float = Field(default=50, gt=0, alias="MAX_UPLOAD_MB")
    # The most pixels one page may take when it is rendered for the model (at 200 DPI: A4 is 3.9 megapixels, A1 31). A PDF is
    # cheap to make with a page the size of a billboard; the render of one needs gigabytes. Refused at upload and again before the render.
    max_page_megapixels: float = Field(default=50, gt=0, alias="MAX_PAGE_MEGAPIXELS")
    max_json_body_kb: float = Field(default=256, gt=0, alias="MAX_JSON_BODY_KB")
    max_documents_per_bundle: int = Field(default=20, ge=1, alias="MAX_DOCUMENTS_PER_BUNDLE")
    max_reference_chars: int = Field(default=200, ge=1, alias="MAX_REFERENCE_CHARS")
    # Corrections by the authorised agent (audit entries) one bundle may hold; a bound on the audit chain, not a workflow limit
    max_corrections_per_bundle: int = Field(default=500, ge=1, alias="MAX_CORRECTIONS_PER_BUNDLE")

    # Abuse and cost control; 0 switches a limit off. The per-minute limits are counted in this process ("memory": demo and one
    # instance) or in Firestore ("firestore": shared by every instance). MAX_CONCURRENT_RUNS caps the runs of THIS process; with
    # RUN_DISPATCH=cloudtasks the cap for the whole service is the queue's max-concurrent-dispatches (infra/tasks/setup_queue.sh).
    rate_limit_writes_per_minute: int = Field(default=60, ge=0, alias="RATE_LIMIT_WRITES_PER_MINUTE")
    rate_limit_runs_per_minute: int = Field(default=10, ge=0, alias="RATE_LIMIT_RUNS_PER_MINUTE")
    rate_limit_backend: Literal["memory", "firestore"] = Field(default="memory", alias="RATE_LIMIT_BACKEND")
    max_concurrent_runs: int = Field(default=4, ge=0, alias="MAX_CONCURRENT_RUNS")
    # Model tokens the whole service may spend per UTC day (services/token_budget.py): counted as runs end and relevance checks are made,
    # checked when an analysis or reassessment starts and before a relevance check asks the model. 0 switches it off. A placeholder, not a
    # price or a quota: 5,000,000 is about 180 four-document analyses (27,315 tokens each, measured); set what the owner is willing to spend.
    daily_token_budget: int = Field(default=5_000_000, ge=0, alias="DAILY_TOKEN_BUDGET")
    # Key the rate limits by the first valid IP of X-Forwarded-For instead of the socket peer. Only turn this on behind
    # a proxy that overwrites the header: the first entry is whatever the client sent.
    trust_forwarded_for: bool = Field(default=False, alias="TRUST_FORWARDED_FOR")
    # Name of a request header that carries the END USER's IP, set by a trusted caller (the UI's server-side proxy
    # when the API is private and only that proxy can reach it). Only set it when nobody else can send requests:
    # the header is taken as written. Unset = the socket peer (or X-Forwarded-For, see above).
    client_ip_header: str | None = Field(default=None, alias="CLIENT_IP_HEADER")

    # /docs, /redoc and /openapi.json. None = on in demo mode, off in live mode.
    enable_api_docs: bool | None = Field(default=None, alias="ENABLE_API_DOCS")

    # How the stage loop is driven (services/engines.py): the plain loop, or the optional google-adk Workflow.
    # Anything else is a startup error. "adk" needs the separate ADK lock (requirements-adk.txt).
    pipeline_engine: Literal["native", "adk"] = Field(default="native", alias="PIPELINE_ENGINE")

    # Preprocessing (services/preprocess.py). PAGE_IMAGE_MODE is what the model is shown: "bw" (1-bit, the original input) or
    # "gray" (8-bit grayscale); the A/B between them is scripts/live_smoke_extraction.py --page-mode. PREPROCESS_DESKEW straightens
    # a skewed scan (a measured skew between the min and max below) and records the reversible transform, so evidence boxes still
    # land on the original page; off by default until the A/B has shown it helps on the real model. PERSIST_PROCESSED_PAGES keeps
    # the page images the model was shown (GET /documents/{id}/pages/{n}): "what did it see" is answerable afterwards.
    page_image_mode: Literal["bw", "gray"] = Field(default="bw", alias="PAGE_IMAGE_MODE")
    preprocess_deskew: bool = Field(default=False, alias="PREPROCESS_DESKEW")
    deskew_min_degrees: float = Field(default=0.3, ge=0, alias="DESKEW_MIN_DEGREES")
    deskew_max_degrees: float = Field(default=10.0, gt=0, le=45, alias="DESKEW_MAX_DEGREES")
    persist_processed_pages: bool = Field(default=True, alias="PERSIST_PROCESSED_PAGES")

    # Audit signing (services/signing.py): after each completed assessment the head of the audit chain is signed with this Cloud
    # KMS asymmetric key VERSION (an EC_SIGN_P256_SHA256 key; the full resource name .../cryptoKeyVersions/N). Unset: demo mode
    # signs with a throwaway local key (labelled as such), live mode does not sign and says so.
    signing_key_version: str | None = Field(default=None, alias="SIGNING_KEY_VERSION")
    audit_signing: bool = Field(default=True, alias="AUDIT_SIGNING")  # false switches signing off altogether

    # CORS
    allowed_origins: str = Field(
        default="http://localhost:3000",
        alias="ALLOWED_ORIGINS",
    )

    # Authentication & Multi-Tenancy (gateway/auth.py)
    auth_enabled: bool = Field(default=True, alias="AUTH_ENABLED")
    oauth_client_id: str | None = Field(default=None, alias="OAUTH_CLIENT_ID")
    oauth_issuer: str = Field(default="https://accounts.google.com", alias="OAUTH_ISSUER")
    allowed_email_domains: str = Field(default="*", alias="ALLOWED_EMAIL_DOMAINS")


    @model_validator(mode="after")
    def _pages_sent_fit_the_request(self) -> "Settings":
        if self.max_pages_sent > self.gemini_max_pages:
            raise ValueError(f"MAX_PAGES_SENT ({self.max_pages_sent}) cannot exceed GEMINI_MAX_PAGES ({self.gemini_max_pages})")
        return self

    @model_validator(mode="after")
    def _stale_window_covers_the_heartbeat(self) -> "Settings":
        """A live run must be able to miss two heartbeats without being declared dead."""
        if self.run_stale_after_seconds < 3 * self.run_heartbeat_seconds:
            raise ValueError(
                f"RUN_STALE_AFTER_SECONDS ({self.run_stale_after_seconds:g}) must be at least 3 x "
                f"RUN_HEARTBEAT_SECONDS ({self.run_heartbeat_seconds:g}) = {3 * self.run_heartbeat_seconds:g}"
            )
        if self.app_mode == "live" and not self.auth_enabled:
            raise ValueError("AUTH_ENABLED must be true when APP_MODE=live")
        if self.app_mode == "live" and not self.oauth_client_id:
            raise ValueError("OAUTH_CLIENT_ID must be configured when APP_MODE=live")
        return self

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def api_docs_enabled(self) -> bool:
        """Explicit ENABLE_API_DOCS wins; otherwise the docs are on in demo mode and off in live mode."""
        if self.enable_api_docs is not None:
            return self.enable_api_docs
        return self.app_mode == "demo"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def allowed_domains_list(self) -> list[str]:
        return [d.strip().lower() for d in self.allowed_email_domains.split(",") if d.strip()]


    @property
    def tariff_table_fqn(self) -> str:
        """Fully-qualified BigQuery table name."""
        return f"{self.project_id}.{self.bq_dataset}.{self.bq_table_tariff}"

    @property
    def embedding_model_fqn(self) -> str:
        """Fully-qualified BigQuery embedding model name."""
        return f"{self.project_id}.{self.bq_dataset}.{self.bq_model_embedding}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Module-level singleton for convenience import
settings: Settings = get_settings()

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
    # tokens the model may spend thinking; 0 disables it, a NEGATIVE value means "do not send the field"
    gemini_thinking_budget: int = Field(default=0, alias="GEMINI_THINKING_BUDGET")
    gemini_max_request_mb: float = Field(default=18, gt=0, alias="GEMINI_MAX_REQUEST_MB")
    gemini_max_pages: int = Field(default=30, ge=1, alias="GEMINI_MAX_PAGES")

    # Run lifecycle (services/orchestrator.py): the API runs as ONE instance; a run proves it is alive by touching
    # its run record every RUN_HEARTBEAT_SECONDS, and a RUNNING record untouched for RUN_STALE_AFTER_SECONDS is dead.
    run_heartbeat_seconds: float = Field(default=10, gt=0, alias="RUN_HEARTBEAT_SECONDS")
    run_stale_after_seconds: float = Field(default=90, gt=0, alias="RUN_STALE_AFTER_SECONDS")
    run_timeout_seconds: float = Field(default=1200, gt=0, alias="RUN_TIMEOUT_SECONDS")

    # SSE stream (api/v1/stream.py): poll fast while a run is active, slowly otherwise
    stream_poll_active_seconds: float = Field(default=1.0, gt=0, alias="STREAM_POLL_ACTIVE_SECONDS")
    stream_poll_idle_seconds: float = Field(default=3.0, gt=0, alias="STREAM_POLL_IDLE_SECONDS")

    # Request and upload limits (gateway/limits.py, api/v1/documents.py, domain/schemas.py::CreateBundleRequest)
    max_upload_mb: float = Field(default=50, gt=0, alias="MAX_UPLOAD_MB")
    max_json_body_kb: float = Field(default=256, gt=0, alias="MAX_JSON_BODY_KB")
    max_documents_per_bundle: int = Field(default=20, ge=1, alias="MAX_DOCUMENTS_PER_BUNDLE")
    max_reference_chars: int = Field(default=200, ge=1, alias="MAX_REFERENCE_CHARS")

    # Abuse and cost control. ONE API instance, so these are in-process; 0 switches a limit off.
    rate_limit_writes_per_minute: int = Field(default=60, ge=0, alias="RATE_LIMIT_WRITES_PER_MINUTE")
    rate_limit_runs_per_minute: int = Field(default=10, ge=0, alias="RATE_LIMIT_RUNS_PER_MINUTE")
    max_concurrent_runs: int = Field(default=4, ge=0, alias="MAX_CONCURRENT_RUNS")
    # Key the rate limits by the first valid IP of X-Forwarded-For instead of the socket peer. Only turn this on behind
    # a proxy that overwrites the header: the first entry is whatever the client sent.
    trust_forwarded_for: bool = Field(default=False, alias="TRUST_FORWARDED_FOR")

    # /docs, /redoc and /openapi.json. None = on in demo mode, off in live mode.
    enable_api_docs: bool | None = Field(default=None, alias="ENABLE_API_DOCS")

    # How the stage loop is driven (services/engines.py): the plain loop, or the optional google-adk Workflow.
    # Anything else is a startup error. "adk" needs the separate ADK lock (requirements-adk.txt).
    pipeline_engine: Literal["native", "adk"] = Field(default="native", alias="PIPELINE_ENGINE")

    # CORS
    allowed_origins: str = Field(
        default="http://localhost:3000",
        alias="ALLOWED_ORIGINS",
    )

    @model_validator(mode="after")
    def _stale_window_covers_the_heartbeat(self) -> "Settings":
        """A live run must be able to miss two heartbeats without being declared dead."""
        if self.run_stale_after_seconds < 3 * self.run_heartbeat_seconds:
            raise ValueError(
                f"RUN_STALE_AFTER_SECONDS ({self.run_stale_after_seconds:g}) must be at least 3 x "
                f"RUN_HEARTBEAT_SECONDS ({self.run_heartbeat_seconds:g}) = {3 * self.run_heartbeat_seconds:g}"
            )
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

"""Application configuration via pydantic-settings."""

from functools import lru_cache
from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # GCP Core
    project_id: str = Field(default="cargoclear-hackathon", alias="PROJECT_ID")
    region: str = Field(default="asia-south1", alias="REGION")

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

    # CORS
    allowed_origins: str = Field(
        default="http://localhost:3000",
        alias="ALLOWED_ORIGINS",
    )

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

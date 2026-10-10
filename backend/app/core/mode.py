"""App mode helper — centralizes live GCP vs demo mode checks.

In "live" mode (APP_MODE=live and GCP credentials present):
  - Live GCP services (Vertex AI, Firestore, BigQuery, GCS) are used.
  - Failures in client init or API calls raise exceptions.
  - Fallbacks to fixtures or in-memory stores are disabled.

In "demo" mode (default):
  - Local/in-memory fallbacks and fixture generators are allowed.
  - Test suites execute hermetically without GCP credentials.

Credentials count as present when ANY of these is true (checked by presence only: no google.auth.default() call,
no network, no metadata-server probe, and the contents of a credential file are never read):
  1. GOOGLE_APPLICATION_CREDENTIALS is set, in the process environment OR in `.env` (pydantic-settings reads `.env`
     into ``settings.google_application_credentials``, not into os.environ, so it is exported here for the Google
     client libraries) AND the file it names exists. A variable that points nowhere makes the Google libraries
     fail, so it is reported as "no credentials" and the message names the missing path;
  2. K_SERVICE is set (Cloud Run: the service identity supplies them);
  3. the gcloud ADC file exists (`gcloud auth application-default login`), under $CLOUDSDK_CONFIG or
     ~/.config/gcloud.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.core.config import settings

ADC_FILE_NAME = "application_default_credentials.json"

NO_CREDENTIALS_MESSAGE = (
    "Live GCP mode requested (APP_MODE=live) but no GCP credentials found. Supply them in one of three ways: "
    "(1) set GOOGLE_APPLICATION_CREDENTIALS to a service-account key file; "
    "(2) run `gcloud auth application-default login` to create application-default credentials; "
    "(3) run on Cloud Run, where the service identity provides them (K_SERVICE is set)."
)


def _adc_file_exists() -> bool:
    """True if `gcloud auth application-default login` has written its credentials file (existence only)."""
    config_dir = os.getenv("CLOUDSDK_CONFIG") or str(Path.home() / ".config" / "gcloud")
    return (Path(config_dir) / ADC_FILE_NAME).is_file()


def _explicit_credentials_path() -> str | None:
    """GOOGLE_APPLICATION_CREDENTIALS from the process environment, else from settings (`.env`); None if unset/blank."""
    value = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or settings.google_application_credentials
    value = value.strip() if value else ""
    return value or None


def _missing_credentials_path() -> str | None:
    """The configured key-file path when it is set but no file exists there; else None."""
    path = _explicit_credentials_path()
    return path if path and not Path(path).is_file() else None


def no_credentials_message() -> str:
    """The "no GCP credentials" error text; names the missing path when GOOGLE_APPLICATION_CREDENTIALS is the problem."""
    missing = _missing_credentials_path()
    if missing is None:
        return NO_CREDENTIALS_MESSAGE
    return f"{NO_CREDENTIALS_MESSAGE} GOOGLE_APPLICATION_CREDENTIALS points to '{missing}', which does not exist."


def credential_source() -> str | None:
    """Name of the credential source that is present, or None. Never returns any credential content."""
    explicit = _explicit_credentials_path()
    if explicit:
        if not Path(explicit).is_file():
            return None  # a variable that points nowhere breaks Google's lookup; it does not fall through to the rest
        os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", explicit)  # so that google.auth.default() sees a .env value
        return "GOOGLE_APPLICATION_CREDENTIALS env var"
    if os.getenv("K_SERVICE"):
        return "Cloud Run service identity (K_SERVICE)"
    if _adc_file_exists():
        return "gcloud application-default credentials file"
    return None


def use_live_gcp() -> bool:
    """Return True if live GCP services should be used."""
    if settings.app_mode != "live":
        return False
    return credential_source() is not None

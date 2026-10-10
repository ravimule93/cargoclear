"""use_live_gcp(): live mode needs credentials, and `gcloud auth application-default login` counts as having them.

Detection is by FILE EXISTENCE only: no google.auth.default() call, no network, no metadata-server probe.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core import mode
from app.core.config import settings
from app.core.mode import credential_source, use_live_gcp

# Bound at import time, i.e. before conftest's autouse fixture replaces mode._adc_file_exists.
real_adc_file_exists = mode._adc_file_exists

ADC_FILE = "application_default_credentials.json"


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_mode", "live")


@pytest.fixture
def key_file(tmp_path) -> Path:
    """A key file that EXISTS (an empty one: its content is never read). A path only counts if the file exists."""
    path = tmp_path / "service-account-key.json"
    path.write_text("")
    return path


def _only(monkeypatch: pytest.MonkeyPatch, source: str | None, key: Path | None = None) -> None:
    """Exactly one credential source is present (or none)."""
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.setattr(settings, "google_application_credentials", None)
    monkeypatch.setattr(mode, "_adc_file_exists", lambda: source == "adc")
    if source == "env":
        assert key is not None, "an env-var source needs a key file that exists"
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(key))
    if source == "cloud_run":
        monkeypatch.setenv("K_SERVICE", "cargoclear-api")


# ---------------------------------------------------------------------------
# the three sources
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source", ["env", "adc", "cloud_run"])
def test_each_credential_source_alone_makes_live_mode_available(live, monkeypatch, key_file, source) -> None:
    _only(monkeypatch, source, key_file)
    assert use_live_gcp() is True


def test_gcloud_adc_login_alone_makes_live_mode_available(live, monkeypatch, tmp_path) -> None:
    """`gcloud auth application-default login` sets NO environment variable; it only writes this file."""
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(tmp_path))
    (tmp_path / ADC_FILE).write_text("{}")
    monkeypatch.setattr(mode, "_adc_file_exists", real_adc_file_exists)  # undo the hermetic fixture for this test

    assert use_live_gcp() is True


def test_no_credential_source_means_no_live_gcp(live, monkeypatch) -> None:
    _only(monkeypatch, None)
    assert use_live_gcp() is False


@pytest.mark.parametrize("app_mode", ["demo"])
def test_demo_mode_is_never_live_even_with_every_source_present(monkeypatch, key_file, app_mode) -> None:
    monkeypatch.setattr(settings, "app_mode", app_mode)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(key_file))
    monkeypatch.setenv("K_SERVICE", "cargoclear-api")
    monkeypatch.setattr(mode, "_adc_file_exists", lambda: True)

    assert use_live_gcp() is False


@pytest.mark.parametrize("value", ["", None])
def test_empty_environment_variables_do_not_count(live, monkeypatch, value) -> None:
    _only(monkeypatch, None)
    if value is not None:
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", value)
        monkeypatch.setenv("K_SERVICE", value)
    assert use_live_gcp() is False


# ---------------------------------------------------------------------------
# which source was detected (for the smoke script; never any key content)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [("env", "GOOGLE_APPLICATION_CREDENTIALS env var"), ("cloud_run", "Cloud Run service identity (K_SERVICE)"),
     ("adc", "gcloud application-default credentials file"), (None, None)],
)
def test_credential_source_names_the_source(monkeypatch, key_file, source, expected) -> None:
    _only(monkeypatch, source, key_file)
    assert credential_source() == expected


def test_credential_source_prefers_the_explicit_key_then_cloud_run_then_the_adc_file(monkeypatch, key_file) -> None:
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(key_file))
    monkeypatch.setenv("K_SERVICE", "cargoclear-api")
    monkeypatch.setattr(mode, "_adc_file_exists", lambda: True)
    assert credential_source() == "GOOGLE_APPLICATION_CREDENTIALS env var"

    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS")
    assert credential_source() == "Cloud Run service identity (K_SERVICE)"

    monkeypatch.delenv("K_SERVICE")
    assert credential_source() == "gcloud application-default credentials file"


def test_credential_source_does_not_depend_on_the_app_mode(monkeypatch, key_file) -> None:
    _only(monkeypatch, "env", key_file)
    monkeypatch.setattr(settings, "app_mode", "demo")
    assert credential_source() == "GOOGLE_APPLICATION_CREDENTIALS env var"  # it reports; use_live_gcp() decides


# ---------------------------------------------------------------------------
# the ADC file check itself: existence only
# ---------------------------------------------------------------------------


def test_the_adc_file_is_found_under_cloudsdk_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(tmp_path))
    assert real_adc_file_exists() is False

    (tmp_path / ADC_FILE).write_text("{}")  # content is irrelevant and never read
    assert real_adc_file_exists() is True


def test_without_cloudsdk_config_the_home_gcloud_directory_is_used(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("CLOUDSDK_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert real_adc_file_exists() is False

    (tmp_path / ".config" / "gcloud").mkdir(parents=True)
    (tmp_path / ".config" / "gcloud" / ADC_FILE).write_text("{}")
    assert real_adc_file_exists() is True


def test_a_directory_with_the_adc_file_name_is_not_a_credential(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(tmp_path))
    (tmp_path / ADC_FILE).mkdir()
    assert real_adc_file_exists() is False


def test_cloudsdk_config_wins_over_the_home_directory(monkeypatch, tmp_path) -> None:
    home, other = tmp_path / "home", tmp_path / "other"
    (home / ".config" / "gcloud").mkdir(parents=True)
    (home / ".config" / "gcloud" / ADC_FILE).write_text("{}")
    other.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(other))

    assert real_adc_file_exists() is False  # CLOUDSDK_CONFIG is consulted instead of ~/.config/gcloud


def test_detection_never_calls_google_auth_or_the_network(live, monkeypatch, tmp_path) -> None:
    import google.auth

    def forbidden(*_a, **_k):
        raise AssertionError("credential detection must be file-existence only")

    monkeypatch.setattr(google.auth, "default", forbidden)
    monkeypatch.setattr(mode, "_adc_file_exists", real_adc_file_exists)
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(tmp_path))
    (tmp_path / ADC_FILE).write_text("{}")
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)

    assert use_live_gcp() is True


# ---------------------------------------------------------------------------
# the test suite can never be made live by a developer's real ADC file (tests/conftest.py)
# ---------------------------------------------------------------------------


def test_the_hermetic_fixture_hides_a_real_adc_file(live, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(tmp_path))
    (tmp_path / ADC_FILE).write_text("{}")
    assert real_adc_file_exists() is True  # the file is really there ...

    assert mode._adc_file_exists() is False  # ... but the autouse fixture forces the detection off
    assert use_live_gcp() is False


# ---------------------------------------------------------------------------
# the error message names the ways to supply credentials
# ---------------------------------------------------------------------------


def test_the_no_credentials_message_names_the_three_ways() -> None:
    message = mode.NO_CREDENTIALS_MESSAGE
    assert message.startswith("Live GCP mode requested (APP_MODE=live) but no GCP credentials found.")
    assert "GOOGLE_APPLICATION_CREDENTIALS" in message
    assert "gcloud auth application-default login" in message
    assert "Cloud Run" in message


@pytest.mark.parametrize(
    "module",
    ["app.agents.extraction", "app.repo.firestore", "app.services.audit", "app.services.storage", "app.agents.tools.bq_tariff"],
)
def test_the_clients_raise_that_message_in_live_mode_without_credentials(live, monkeypatch, module) -> None:
    import importlib

    from app.gateway.errors import UpstreamError

    _only(monkeypatch, None)
    target = importlib.import_module(module)
    getter = {
        "app.agents.extraction": "_get_genai_client",
        "app.repo.firestore": "_get_firestore_client",
        "app.services.audit": "_get_firestore_client",
        "app.services.storage": "_get_gcs_client",
        "app.agents.tools.bq_tariff": "_get_bq_client",
    }[module]

    with pytest.raises(UpstreamError) as raised:
        getattr(target, getter)()

    assert mode.NO_CREDENTIALS_MESSAGE in str(raised.value)


# ---------------------------------------------------------------------------
# A3: GOOGLE_APPLICATION_CREDENTIALS may live in `.env`, and a path counts only if the FILE exists
#
# pydantic-settings reads `.env` into Settings fields, NOT into os.environ, so the variable the .env.example
# tells people to set used to be invisible to mode.py (which only looked at os.environ).
# ---------------------------------------------------------------------------


def test_the_env_var_with_an_existing_file_is_live(live, monkeypatch, key_file) -> None:
    _only(monkeypatch, "env", key_file)

    assert use_live_gcp() is True
    assert credential_source() == "GOOGLE_APPLICATION_CREDENTIALS env var"


def test_the_env_var_with_a_missing_file_is_not_live_and_the_message_names_the_path(live, monkeypatch, tmp_path) -> None:
    missing = tmp_path / "no-such-key.json"
    _only(monkeypatch, None)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(missing))

    assert credential_source() is None
    assert use_live_gcp() is False
    message = mode.no_credentials_message()
    assert message.startswith(mode.NO_CREDENTIALS_MESSAGE)
    assert message.endswith(f"GOOGLE_APPLICATION_CREDENTIALS points to '{missing}', which does not exist.")


def test_a_broken_explicit_variable_wins_over_the_other_sources(live, monkeypatch, tmp_path) -> None:
    """Google's own ADC lookup fails on a variable that points nowhere; it does not fall through to Cloud Run / ADC."""
    _only(monkeypatch, "adc")
    monkeypatch.setenv("K_SERVICE", "cargoclear-api")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path / "no-such-key.json"))

    assert credential_source() is None and use_live_gcp() is False


def test_a_directory_is_not_a_key_file(live, monkeypatch, tmp_path) -> None:
    _only(monkeypatch, None)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path))

    assert use_live_gcp() is False
    assert f"points to '{tmp_path}'" in mode.no_credentials_message()


def test_without_the_variable_the_message_is_the_plain_one(live, monkeypatch) -> None:
    _only(monkeypatch, None)

    assert mode.no_credentials_message() == mode.NO_CREDENTIALS_MESSAGE
    assert "points to" not in mode.no_credentials_message()


def test_a_value_only_in_settings_is_live_and_is_exported_for_the_google_libraries(live, monkeypatch, key_file) -> None:
    _only(monkeypatch, None)
    monkeypatch.setattr(settings, "google_application_credentials", str(key_file))
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ

    assert use_live_gcp() is True
    assert credential_source() == "GOOGLE_APPLICATION_CREDENTIALS env var"
    assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == str(key_file)  # google.auth.default() will now find it


def test_conftest_undoes_that_export_so_nothing_leaks_into_the_next_test() -> None:
    """Runs right after the export test above: the hermetic fixture must have put os.environ back."""
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ
    assert settings.google_application_credentials is None


def test_a_settings_value_pointing_nowhere_is_not_live_and_is_not_exported(live, monkeypatch, tmp_path) -> None:
    _only(monkeypatch, None)
    missing = tmp_path / "no-such-key.json"
    monkeypatch.setattr(settings, "google_application_credentials", str(missing))

    assert use_live_gcp() is False
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ
    assert f"points to '{missing}', which does not exist." in mode.no_credentials_message()


def test_the_process_environment_wins_over_settings_and_is_not_overwritten(live, monkeypatch, key_file, tmp_path) -> None:
    other = tmp_path / "other-key.json"
    other.write_text("")
    _only(monkeypatch, "env", key_file)
    monkeypatch.setattr(settings, "google_application_credentials", str(other))

    assert use_live_gcp() is True
    assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == str(key_file)


def test_an_empty_env_var_falls_back_to_settings(live, monkeypatch, key_file) -> None:
    _only(monkeypatch, None)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    monkeypatch.setattr(settings, "google_application_credentials", str(key_file))

    assert use_live_gcp() is True


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_settings_value_counts_as_unset(live, monkeypatch, blank) -> None:
    _only(monkeypatch, None)
    monkeypatch.setattr(settings, "google_application_credentials", blank)

    assert use_live_gcp() is False
    assert mode.no_credentials_message() == mode.NO_CREDENTIALS_MESSAGE


def test_demo_mode_is_never_live_whatever_settings_say(monkeypatch, key_file) -> None:
    _only(monkeypatch, None)
    monkeypatch.setattr(settings, "google_application_credentials", str(key_file))
    monkeypatch.setattr(settings, "app_mode", "demo")

    assert use_live_gcp() is False
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ, "demo mode must not export anything"


def test_the_adc_file_still_works_when_nothing_else_is_set(live, monkeypatch) -> None:
    _only(monkeypatch, "adc")

    assert use_live_gcp() is True
    assert credential_source() == "gcloud application-default credentials file"


def test_a_dot_env_file_reaches_the_settings_field_but_not_the_environment(monkeypatch, tmp_path, key_file) -> None:
    """The scenario of the bug: the variable is set in `.env`, as .env.example says."""
    from app.core.config import Settings

    dot_env = tmp_path / ".env"
    dot_env.write_text(f"GOOGLE_APPLICATION_CREDENTIALS={key_file}\nAPP_MODE=live\n")
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    loaded = Settings(_env_file=str(dot_env))

    assert loaded.google_application_credentials == str(key_file)
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ  # pydantic-settings never exports it

    monkeypatch.setattr(settings, "app_mode", "live")
    monkeypatch.setattr(settings, "google_application_credentials", loaded.google_application_credentials)
    monkeypatch.setattr(mode, "_adc_file_exists", lambda: False)
    assert use_live_gcp() is True


@pytest.mark.parametrize(
    "module",
    ["app.agents.extraction", "app.repo.firestore", "app.services.audit", "app.services.storage", "app.agents.tools.bq_tariff"],
)
def test_every_client_names_the_missing_path_in_its_error(live, monkeypatch, tmp_path, module) -> None:
    import importlib

    from app.gateway.errors import UpstreamError

    _only(monkeypatch, None)
    missing = tmp_path / "no-such-key.json"
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(missing))
    target = importlib.import_module(module)
    getter = {
        "app.agents.extraction": "_get_genai_client", "app.repo.firestore": "_get_firestore_client",
        "app.services.audit": "_get_firestore_client", "app.services.storage": "_get_gcs_client",
        "app.agents.tools.bq_tariff": "_get_bq_client",
    }[module]

    with pytest.raises(UpstreamError) as raised:
        getattr(target, getter)()

    assert f"GOOGLE_APPLICATION_CREDENTIALS points to '{missing}', which does not exist." in str(raised.value)


def test_the_env_example_comments_the_variable_out_and_explains_the_options() -> None:
    text = (Path(__file__).resolve().parents[2] / ".env.example").read_text()
    lines = text.splitlines()

    assert not [line for line in lines if line.startswith("GOOGLE_APPLICATION_CREDENTIALS=")], "must be commented out"
    assert "# GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/service-account-key.json" in lines
    assert "gcloud auth application-default login" in text and "ABSOLUTE path" in text

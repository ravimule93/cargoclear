"""Release metadata exposed to reviewers must stay explicit and non-sensitive."""

from fastapi.testclient import TestClient

from app import main


def test_version_reports_release_identity(monkeypatch) -> None:
    # The app intentionally imports one validated settings object at process start.
    # Patch that object, rather than changing environment variables too late.
    monkeypatch.setattr(main.settings, "release_sha", "abc123")
    monkeypatch.setattr(main.settings, "release_timestamp", "2026-10-16T00:00:00Z")
    monkeypatch.setattr(main.settings, "app_mode", "live")
    response = TestClient(main.create_app()).get("/version")
    assert response.status_code == 200
    body = response.json()
    assert body["release_sha"] == "abc123"
    assert body["release_timestamp"] == "2026-10-16T00:00:00Z"
    assert body["app_mode"] == "live"
    assert "credentials" not in body

"""Retention configuration is reviewable before an operator applies it."""

import json

from tests.helpers import REPO_ROOT


def test_artifact_lifecycle_is_exactly_ninety_days() -> None:
    policy = json.loads(
        (REPO_ROOT / "infra/storage/cargoclear-artifact-lifecycle-90-days.json").read_text(encoding="utf-8")
    )
    assert policy == {"rule": [{"action": {"type": "Delete"}, "condition": {"age": 90}}]}


def test_retention_setup_is_preview_first_and_excludes_audit_records() -> None:
    script = (REPO_ROOT / "infra/storage/setup_artifact_retention.sh").read_text(encoding="utf-8")
    assert 'APPLY_RETENTION_POLICY:-' in script
    assert '!= "yes"' in script
    assert "Audit records are excluded" in script
    assert "gcloud storage buckets update" in script

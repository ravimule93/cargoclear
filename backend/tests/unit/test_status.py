"""Unit tests for compliance status enum and precedence resolution."""

import pytest
from hypothesis import given, strategies as st

from app.domain.status import Status, resolve_status


class TestStatusPrecedence:
    def test_empty_is_compliant(self):
        assert resolve_status([]) == Status.COMPLIANT_FOR_SUBMISSION

    def test_single_material_contradiction(self):
        assert resolve_status([Status.MATERIAL_CONTRADICTION]) == Status.MATERIAL_CONTRADICTION

    def test_material_wins_over_missing_evidence(self):
        candidates = [Status.MISSING_EVIDENCE, Status.MATERIAL_CONTRADICTION]
        assert resolve_status(candidates) == Status.MATERIAL_CONTRADICTION

    def test_material_wins_over_all(self):
        candidates = [
            Status.COMPLIANT_FOR_SUBMISSION,
            Status.MISSING_EVIDENCE,
            Status.SPECIALIST_REVIEW_REQUIRED,
            Status.MATERIAL_CONTRADICTION,
        ]
        assert resolve_status(candidates) == Status.MATERIAL_CONTRADICTION

    def test_missing_evidence_beats_specialist(self):
        candidates = [Status.SPECIALIST_REVIEW_REQUIRED, Status.MISSING_EVIDENCE]
        assert resolve_status(candidates) == Status.MISSING_EVIDENCE

    def test_specialist_beats_compliant(self):
        candidates = [Status.COMPLIANT_FOR_SUBMISSION, Status.SPECIALIST_REVIEW_REQUIRED]
        assert resolve_status(candidates) == Status.SPECIALIST_REVIEW_REQUIRED

    def test_single_compliant(self):
        assert resolve_status([Status.COMPLIANT_FOR_SUBMISSION]) == Status.COMPLIANT_FOR_SUBMISSION

    def test_idempotent_duplicates(self):
        """Duplicate statuses should not change the result."""
        candidates = [Status.MISSING_EVIDENCE, Status.MISSING_EVIDENCE]
        assert resolve_status(candidates) == Status.MISSING_EVIDENCE


@given(
    st.lists(
        st.sampled_from(list(Status)),
        min_size=0,
        max_size=10,
    )
)
def test_resolve_status_always_returns_valid_status(candidates):
    """Property: resolve_status always returns a valid Status value."""
    result = resolve_status(candidates)
    assert result in Status
